#!/usr/bin/env python3
"""User-run serialized E04-0 collection; preserves failures and resumes by job.

No training/export/dependency/power/control changes. A completed collection still
requires coordinator review before the E04-0 gate or sub-agent development.
"""
import argparse
import csv
import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
import re

from audit_robot import EXPECTED_E01, sha256, write_json, read_text


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def verify_sources(contract):
    changed = [x['path'] for x in contract['sources'] if not Path(x['path']).is_file()
               or sha256(Path(x['path'])) != x['sha256']]
    if changed:
        raise RuntimeError('Audited source/config changed; review before measuring: ' + repr(changed))
    if sha256(Path(contract['engine_source'])) != EXPECTED_E01:
        raise RuntimeError('Original E01 Engine differs from E03')
    cap = read_text('/sys/devices/17000000.ga10b/devfreq/17000000.ga10b/max_freq')
    if cap != '408000000':
        raise RuntimeError('GPU cap differs from audited 408 MHz; do not adjust it automatically: ' + str(cap))


def conflicting_processes():
    result = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit() or int(path.name) == os.getpid():
            continue
        try:
            args = (path / 'cmdline').read_bytes().split(b'\0')
            comm = (path / 'comm').read_text().strip()
            text = b' '.join(args).decode(errors='replace')
            if comm in ['trtexec', 'nsys', 'ZED_Explorer'] or any(x in text for x in
                    ['soccer_perception_ros_node.py', 'model_benchmark/benchmark.py', 'model_benchmark/worker.py']):
                result.append(dict(pid=int(path.name), name=comm))
            environment = (path / 'environ').read_bytes().split(b'\0')
            if b'ROS_DOMAIN_ID=87' in environment and ('ros2' in comm or 'soccer_perception_ros_node.py' in text):
                result.append(dict(pid=int(path.name), name=comm, reason='test ROS domain87 already occupied'))
        except (OSError, PermissionError):
            continue
    return result


def telemetry(run, done):
    gpu = Path('/sys/devices/17000000.ga10b')
    with (run / 'telemetry_stage0.jsonl').open('a', buffering=1) as stream:
        while not done.is_set():
            value = dict(utc=utc(), monotonic=time.monotonic(), gpu_hz=read_text(gpu / 'devfreq/17000000.ga10b/cur_freq'),
                         gpu_load_per_mille=read_text(gpu / 'load'), loadavg=os.getloadavg(),
                         thermal={read_text(p / 'type'): read_text(p / 'temp') for p in Path('/sys/class/thermal').glob('thermal_zone*')})
            stream.write(json.dumps(value) + '\n')
            done.wait(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--with-system', action='store_true', help='Run only while robot is stationary and camera is free')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='CPU-only identity checks and command plan; no GPU/camera/ROS')
    args = parser.parse_args()
    run, project = args.run_dir.resolve(), args.project.resolve()
    if (project / 'results/E04_tensorrt_pipeline').resolve() not in run.parents:
        raise ValueError('Run must be inside the independent E04 results tree')
    contract = json.loads((run / 'frozen_contract.json').read_text())
    verify_sources(contract)
    from soccer_perception.ros.node import config_from_ros_params
    current_parameters = {k: str(v) if isinstance(v, Path) else v for k, v in vars(config_from_ros_params()).items()}
    if current_parameters != contract['parameters']:
        raise RuntimeError('Effective configuration differs from audited configuration')
    power = subprocess.check_output(['nvpmodel', '-q'], stderr=subprocess.STDOUT, universal_newlines=True)
    if not re.search(r'NV Power Mode:\s*25W\b', power):
        raise RuntimeError('Power mode differs from audited 25W; do not change it automatically')
    if not args.with_system and not args.dry_run:
        parser.error('Formal stage0 requires --with-system in a safe stationary test window')
    plan = ['golden: 100 warmup + all fixed native Val pairs and current camera calibration',
            'existing benchmark: original E01 Engine and current system, each 3 x 60s, 100 warmup',
            'fixed-pair detector: 3 x 60s, 100 warmup, method walls and full detector wall',
            'verify all original Engine/PT/ONNX files and freeze outputs for review']
    if args.dry_run:
        print(json.dumps(dict(dry_run=True, gpu_work=False, camera_work=False, plan=plan,
                             stage0_gate='not_passed', contract=sha256(run / 'frozen_contract.json')), indent=2))
        return 0
    if os.environ.get('ROS_DOMAIN_ID') != '87' or os.environ.get('ROS_LOCALHOST_ONLY') != '1':
        raise RuntimeError('Use the supplied launcher: ROS_DOMAIN_ID=87 and ROS_LOCALHOST_ONLY=1 required')
    lock = (run.parent / 'gpu_benchmark.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    conflicts = conflicting_processes()
    if conflicts:
        raise RuntimeError('Other benchmark/vision/test-domain task detected; no process stopped: ' + repr(conflicts))
    if (run / 'STAGE0_COLLECTION_COMPLETE.json').exists():
        raise FileExistsError('Collection already completed; do not overwrite it')
    history_path = run / 'stage0_jobs.json'
    if history_path.exists() and not args.resume:
        raise FileExistsError('Earlier attempt exists; inspect logs and use --resume to retain completed jobs')
    jobs = json.loads(history_path.read_text()) if history_path.exists() else []
    fixed_contract = sha256(run / 'frozen_contract.json')
    if any(x.get('contract_sha256') != fixed_contract for x in jobs):
        raise RuntimeError('Resume contract differs from earlier attempt')
    frozen = run / 'frozen_models/E01_baseline.engine'
    frozen.parent.mkdir(exist_ok=True)
    if not frozen.exists():
        shutil.copyfile(contract['engine_source'], frozen)
    if sha256(frozen) != EXPECTED_E01:
        raise RuntimeError('Frozen copy differs')
    protected = {}
    for base in [project / 'soccer_perception_ros/models', project / 'install/soccer_perception_ros/share/soccer_perception_ros/models']:
        for p in base.glob('*'):
            if p.is_file() and p.suffix in ['.engine', '.pt', '.onnx']:
                protected[str(p)] = sha256(p)
    if (run / 'protected_models_before.json').exists():
        if json.loads((run / 'protected_models_before.json').read_text()) != protected:
            raise RuntimeError('Original models changed since earlier attempt')
    else:
        write_json(run / 'protected_models_before.json', protected)
    with (run / 'power_stage0.txt').open('a') as power_log:
        power_log.write(utc() + '\n' + power + '\n')
    done = threading.Event()
    thread = threading.Thread(target=telemetry, args=(run, done), daemon=True); thread.start()

    def job(name, make_command):
        if any(x['name'] == name and x['status'] == 'complete' for x in jobs):
            print('[SKIP completed] ' + name, flush=True); return
        verify_sources(contract)
        attempt = 1 + sum(x['name'] == name for x in jobs)
        output = run / ('stage0_' + name + '_attempt%d' % attempt)
        record = dict(name=name, attempt=attempt, status='running', started_utc=utc(),
                      output=str(output), contract_sha256=fixed_contract)
        jobs.append(record); write_json(history_path, jobs)
        command = make_command(output)
        record['command'] = command
        print('[RUN] ' + name + ' -> ' + str(output), flush=True)
        with (run / (name + '_attempt%d.log' % attempt)).open('w', buffering=1) as log:
            proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, pass_fds=(lock.fileno(),))
            record['pid'] = proc.pid; write_json(history_path, jobs)
            try:
                code = proc.wait()
            except BaseException:
                # Own child process group only; worker's existing PDEATHSIG handles descendants.
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=20)
                record.update(status='interrupted', completed_utc=utc()); write_json(history_path, jobs)
                raise
        record.update(status='complete' if code == 0 else 'failed', returncode=code, completed_utc=utc())
        write_json(history_path, jobs)
        if code:
            raise RuntimeError(name + ' failed; inspect its log, retain output and resume explicitly')
        print('[DONE] ' + name, flush=True)

    try:
        job('golden', lambda output: [sys.executable, '-u', str(run / 'scripts/stage0_replay.py'), '--run-dir', str(run),
                                      '--output', str(output), '--mode', 'golden'])
        def benchmark(output):
            config = dict(models=[dict(name='R0_E01', path=str(frozen))], baseline='R0_E01',
                          test=dict(mode='both', rounds=3, warmup_iterations=100, duration_seconds=60, input_shape='auto', seed=42),
                          system=dict(publish_rate_hz=contract['parameters']['deploy_packet_rate_hz'],
                                      viser_enabled=contract['parameters']['zed_viser_enabled'],
                                      point_cloud_enabled=contract['parameters']['zed_viser_show_point_cloud'],
                                      ros_domain_id=87, parameter_overrides={}),
                          output=dict(directory=str(output), save_frame_records=True))
            path = run / ('config_' + output.name + '.yaml')
            write_json(path, config)  # JSON is valid YAML, parsed by existing strict loader.
            return ['bash', str(project / 'tool/model_benchmark/run.sh'), '--config', str(path)]
        job('engine_system', benchmark)
        for index in range(1, 4):
            job('detector_r%d' % index, lambda output: [sys.executable, '-u', str(run / 'scripts/stage0_replay.py'),
                 '--run-dir', str(run), '--output', str(output), '--mode', 'detector', '--warmup', '100', '--seconds', '60'])
        verify_sources(contract)
        after = {p: sha256(p) for p in protected}
        if after != protected:
            raise RuntimeError('Original model content changed; stop and investigate')
        write_json(run / 'protected_models_after.json', after)
        import numpy as np
        summaries = []
        for record in jobs:
            if record['status'] != 'complete' or record['name'] == 'golden':
                continue
            for path in Path(record['output']).rglob('frames.csv'):
                with path.open() as stream:
                    rows = list(csv.DictReader(stream))
                for metric in rows[0] if rows else []:
                    if not metric.endswith('_ms'):
                        continue
                    values = np.asarray([float(row[metric]) for row in rows])
                    summaries.append(dict(job=record['name'], file=str(path), metric=metric, n=len(values),
                         mean=float(values.mean()), p50=float(np.percentile(values, 50)),
                         p95=float(np.percentile(values, 95)), p99=float(np.percentile(values, 99))))
        write_json(run / 'stage0_metric_distributions.json', summaries)
        write_json(run / 'STAGE0_COLLECTION_COMPLETE.json', dict(status='collected_pending_coordinator_review', completed_utc=utc(),
                   stage0_gate='not_passed', original_models_unchanged=True, contract_sha256=fixed_contract,
                   note='Requires Golden/protocol, repeatability, P95/P99 and environment review before A/B/C start.'))
        print('[COLLECTION COMPLETE] ' + str(run / 'STAGE0_COLLECTION_COMPLETE.json'), flush=True)
    except BaseException as exc:
        failure = run / ('STAGE0_FAILURE_' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
        write_json(failure, dict(status='failed_or_interrupted', utc=utc(), error=repr(exc), stage0_gate='not_passed'))
        raise
    finally:
        done.set(); thread.join(timeout=3); lock.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
