#!/usr/bin/env python3
"""User-run E04 single-component CUDA correctness collection, serialized."""
import argparse
import datetime
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading

from performance_runner import run_child


def select_variants(payload, gate=None):
    mode = payload.get('mode', 'single_components')
    if mode == 'single_components':
        return {'R0': {}, 'A1': {'postprocess': 'a1'}, 'A2': {'postprocess': 'a2'},
                'A1_A2': {'postprocess': 'a1+a2'}, 'B_Graph': {'engine': 'graph'},
                'C1_probe': {'preprocess': 'c1'}, 'C2': {'preprocess': 'c2'}}
    if mode == 'ab_combination_correctness':
        if not gate or gate.get('status') != 'approved_for_ab_correctness_only' or gate.get('allowed_switches') != {'postprocess': 'a2', 'engine': 'graph'}:
            raise RuntimeError('Coordinator A2+Graph correctness gate required')
        return {'R0': {}, 'R4_AB': {'postprocess': 'a2', 'engine': 'graph'}}
    if mode == 'ab_abc_combination_correctness':
        allowed = {'R4_AB': {'postprocess': 'a2', 'engine': 'graph'},
                   'R5_ABC': {'postprocess': 'a2', 'engine': 'graph', 'preprocess': 'c2'}}
        if not gate or gate.get('status') != 'approved_for_ab_abc_correctness_only' or gate.get('allowed_combinations') != allowed:
            raise RuntimeError('Coordinator A2+Graph/C2 diagnostic correctness gate required')
        return dict(R0={}, **allowed)
    raise ValueError('Unknown correctness mode: ' + repr(mode))


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--phase-dir', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    run, phase = args.run_dir.resolve(), args.phase_dir.resolve()
    if phase.parent != run or run.parent.name != 'E04_tensorrt_pipeline':
        raise ValueError('Independent E04 phase directory required')
    sys.path.insert(0, str(run / 'scripts'))
    from stage0_robot import verify_sources, conflicting_processes, telemetry
    contract = json.loads((run / 'frozen_contract.json').read_text())
    payload = json.loads((phase / 'phase_manifest.json').read_text())
    fingerprint = digest(phase / 'phase_manifest.json')
    combination = payload.get('mode') in ('ab_combination_correctness', 'ab_abc_combination_correctness')
    def verify():
        verify_sources(contract)
        for item in payload['files']:
            path = (phase / item['path']).resolve()
            if phase not in path.parents or digest(path) != item['sha256']:
                raise RuntimeError('Candidate payload changed: ' + str(path))
        for item in payload.get('reference_files', []):
            path = (run / item['path']).resolve()
            if run not in path.parents or digest(path) != item['sha256']:
                raise RuntimeError('Frozen input/reference changed: ' + str(path))
        if payload.get('distribution_versions'):
            actual = {name: importlib.metadata.version(name) for name in payload['distribution_versions']}
            if actual != payload['distribution_versions']:
                raise RuntimeError('Runtime distributions changed')
            import cv2
            if cv2.__version__ != payload['opencv_version']:
                raise RuntimeError('OpenCV runtime changed')
        if combination:
            origin = run / payload['tested_source_phase']
            if digest(origin / 'phase_manifest.json') != payload['tested_source_manifest_sha256']:
                raise RuntimeError('Previously tested candidate source identity changed')
            old_manifest = json.loads((origin / 'phase_manifest.json').read_text())
            frozen_source = {i['path']: i['sha256'] for i in old_manifest['files'] if i['path'].startswith('source/')}
            copied_source = {i['path']: i['sha256'] for i in payload['files'] if i['path'].startswith('source/')}
            if not frozen_source or copied_source != frozen_source:
                raise RuntimeError('Combination source must exactly match every tested source file')
            completed = json.loads((origin / 'CORRECTNESS_COLLECTION_COMPLETE.json').read_text())
            if completed['payload_sha256'] != payload['tested_source_manifest_sha256'] or not all(v == 'passed' for v in completed['jobs'].values()):
                raise RuntimeError('Single-component correctness evidence missing')
        if digest(run / 'frozen_models/E01_baseline.engine') != '98c1b6bc703b29874d95db94d9cf51ef5b4a4142a7ca6cf22362a0c616fbf348':
            raise RuntimeError('Frozen Engine differs')
        from soccer_perception.ros.node import config_from_ros_params
        config = {k: str(v) if isinstance(v, Path) else v for k, v in vars(config_from_ros_params()).items()}
        if config != contract['parameters']:
            raise RuntimeError('Candidate effective base config differs from frozen deployment')
    verify()
    power = subprocess.check_output(['nvpmodel', '-q'], stderr=subprocess.STDOUT, universal_newlines=True)
    if not re.search(r'NV Power Mode:\s*25W\b', power):
        raise RuntimeError('Power mode differs from frozen 25W; do not adjust it automatically')
    gate = json.loads((phase / 'combination_gate.json').read_text()) if combination else None
    variants = select_variants(payload, gate)
    if args.dry_run:
        print(json.dumps(dict(status='ready', cuda_work=False, camera_work=False, payload_sha256=fingerprint,
                             variants=variants, note='Correctness only. No performance or stability approval.'), indent=2))
        return 0
    if os.environ.get('ROS_DOMAIN_ID') != '87' or os.environ.get('ROS_LOCALHOST_ONLY') != '1':
        raise RuntimeError('Use the supplied isolated launcher')
    lock = (run.parent / 'gpu_benchmark.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if conflicting_processes():
        raise RuntimeError('Other test/vision task found; no process stopped')
    if (phase / 'CORRECTNESS_COLLECTION_COMPLETE.json').exists():
        raise FileExistsError('Already completed; do not rerun')
    history = phase / 'jobs.json'
    if history.exists() and not args.resume:
        raise FileExistsError('Earlier attempt exists; inspect and resume explicitly')
    jobs = json.loads(history.read_text()) if history.exists() else []
    if any(x['payload_sha256'] != fingerprint for x in jobs):
        raise RuntimeError('Resume payload changed')
    protected_before = json.loads((run / 'protected_models_after.json').read_text())
    if any(digest(Path(p)) != h for p, h in protected_before.items()):
        raise RuntimeError('Original model content changed since stage0')
    with (phase / 'power_correctness.txt').open('a') as stream:
        stream.write(datetime.datetime.now(datetime.timezone.utc).isoformat() + '\n' + power + '\n')
    done = threading.Event()
    monitor = threading.Thread(target=telemetry, args=(phase, done), daemon=True)
    monitor.start()

    def job(name, commands):
        old = next((x for x in reversed(jobs) if x['name'] == name and x['status'] == 'passed'), None)
        if old:
            print('[SKIP completed] ' + name, flush=True)
            return True
        verify()
        attempt = 1 + sum(x['name'] == name for x in jobs)
        output = phase / (name + '_attempt%d' % attempt)
        record = dict(name=name, attempt=attempt, status='running', payload_sha256=fingerprint, output=str(output),
                      started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        jobs.append(record); write(history, jobs)
        print('[RUN] ' + name + ' -> ' + str(output), flush=True)
        try:
            for command in commands(output):
                record['command'] = command; write(history, jobs)
                with (phase / (name + '_attempt%d.log' % attempt)).open('a') as log:
                    def started(pid):
                        record['worker_pid'] = pid; write(history, jobs)
                    code = run_child(command, log, lock.fileno(), started, timeout_seconds=240)
                if code:
                    record.update(status='failed_requires_review', returncode=code)
                    break
            else:
                record.update(status='passed', returncode=0)
        except BaseException as error:
            record.update(status='failed_requires_review', error=repr(error))
            record['completed_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            write(history, jobs)
            raise
        record['completed_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        write(history, jobs)
        print('[' + record['status'].upper() + '] ' + name, flush=True)
        return record['status'] == 'passed'

    scripts = phase / 'scripts'
    reference = run / 'stage0_golden_attempt1'
    try:
        graph_ok = True if combination else job('B1_B2_graph', lambda out: [[sys.executable, '-u', str(scripts / 'graph_probe.py'),
                       '--run-dir', str(run), '--output', str(out)]])
        for name, switches in variants.items():
            if name == 'B_Graph' and not graph_ok:
                print('[SKIP] B_Graph: B1/B2 failed; other independent candidates continue', flush=True)
                continue
            config = phase / ('variant_' + name + '.json')
            if config.exists() and json.loads(config.read_text()) != switches:
                raise RuntimeError('Variant config changed')
            if not config.exists(): write(config, switches)
            def commands(out):
                return [[sys.executable, '-u', str(scripts / 'candidate_entry.py'),
                         '--entry', str(run / 'scripts/stage0_replay.py'), '--variant-json', str(config),
                         '--status-file', str(out) + '_hooks.json', '--frozen-calibration', str(reference / 'calibration.json'),
                         '--', '--run-dir', str(run), '--output', str(out), '--mode', 'golden', '--warmup', '100'],
                        [sys.executable, str(scripts / 'compare_goldens.py'), '--reference', str(reference),
                         '--candidate', str(out), '--output', str(out) + '_comparison.json']]
            okay = job(name, commands)
            if name == 'R0' and not okay:
                raise RuntimeError('Repeated R0 failed frozen-reference check; stop candidate collection')
        verify()
        if any(digest(Path(p)) != h for p, h in protected_before.items()):
            raise RuntimeError('Protected model integrity failed')
        latest = {x['name']: x for x in jobs}
        passed = graph_ok and all(latest.get(name, {}).get('status') == 'passed' for name in variants)
        status = dict(status='collected_pending_coordinator_review' if passed else 'collected_with_failures',
                      performance_measured=False, stability_approved=False, production_changed=False,
                      payload_sha256=fingerprint, completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      jobs={k: v['status'] for k, v in latest.items()},
                      mode=payload.get('mode', 'single_components'),
                      note=('Combination correctness only; R5 is diagnostic, no performance/adoption/stability approval or camera opened.' if combination else
                            'A3 unavailable. No A+B/A+B+C, no formal latency measurements, no camera opened.'))
        write(phase / ('CORRECTNESS_COLLECTION_COMPLETE.json' if passed else 'CORRECTNESS_COLLECTION_FINISHED.json'), status)
        print(json.dumps(status, indent=2), flush=True)
        return 0 if passed else 1
    finally:
        done.set(); monitor.join(timeout=3); lock.close()


if __name__ == '__main__':
    raise SystemExit(main())
