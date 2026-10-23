#!/usr/bin/env python3
"""User-run serialized E04 performance collection with frozen matrices."""
import argparse
import datetime
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import threading

from performance_plan import schedule, summarize, matrix_scopes, is_baseline_end
from performance_runner import run_child, supersede_partial_blocks


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def validate_hooks(path, spec, samples, expected_runtime=None):
    value = read(path)
    if value.get('error') or value.get('validation_errors') or len(value.get('detectors', [])) != 1:
        raise RuntimeError('Candidate hook state invalid: ' + str(path))
    detector = value['detectors'][0]
    if detector.get('restore') != 'complete' or detector.get('restore_error'):
        raise RuntimeError('Candidate did not restore safely')
    state = detector['before_restore']['components']
    warm = value['warmup_checkpoint'][0]['components']
    defaults = dict(engine='b0', postprocess='a0', preprocess='c0')
    if expected_runtime is not None:
        identities = value.get('runtime_identity', [])
        if len(identities) != 1 or json.dumps(identities[0], sort_keys=True) != json.dumps(expected_runtime, sort_keys=True):
            raise RuntimeError('Actual detector bindings/parameters/NMS path changed')
    for key, default in defaults.items():
        expected = spec['switches'].get(key, default)
        if any(v[key]['effective'] != expected or v[key]['fallback_count'] for v in [state, warm]):
            raise RuntimeError('Candidate was not effective throughout warmup/measurement: ' + key)
    if spec['switches'].get('engine') == 'graph':
        graph = state['engine']
        if graph['capture_count'] != 1 or graph['replay_count'] != graph['input_update_count'] or graph['replay_count'] != 100 + samples:
            raise RuntimeError('Graph counters mismatch measured sample count')
    if spec['switches'].get('preprocess') == 'c2':
        end, begin = state['preprocess'], warm['preprocess']
        if end['calls'] - begin['calls'] != samples or end['success_count'] - begin['success_count'] != samples or end['host_buffer_allocations'] != begin['host_buffer_allocations'] or end['host_buffer_allocations'] != 1:
            raise RuntimeError('C2 did not reuse one buffer for every current batch')
    if 'a2' in spec['switches'].get('postprocess', ''):
        if state['postprocess']['predict_calls'] - warm['postprocess']['predict_calls'] != samples:
            raise RuntimeError('A2 predict count mismatch')
    if spec['switches'].get('preprocess') == 'c1':
        timings = {}
        for key, end in state['preprocess']['timings'].items():
            begin = warm['preprocess']['timings'][key]
            count = end['count'] - begin['count']
            if count != samples:
                raise RuntimeError('C1 measured segment count mismatch')
            timings[key] = dict(count=count, total_ms=end['total_ms'] - begin['total_ms'],
                                mean_ms=(end['total_ms'] - begin['total_ms']) / count)
        value['measurement_only_c1_timings'] = timings
    return value


def validate_packet_observation(hook, metrics, samples):
    observer = hook.get('packet_observer', {})
    expected_fields = {'frame_idx', 'frame_timestamp_s', 'measurement_valid', 'tracking_valid',
                       'track_initialized', 'coasting', 'frames_since_measurement'}
    if (observer.get('restore') != 'complete' or observer.get('warmup_calls') != 100 or
            observer.get('calls') != 100 + samples or set(observer.get('fields', [])) != expected_fields):
        raise RuntimeError('Packet observation did not match warmup/measured frame count or fields')
    association = metrics.get('frame_association', {})
    if (not metrics.get('packet_flags') or association.get('frame_idx_nonincreasing') != 0 or
            association.get('timestamp_nonincreasing') != 0):
        raise RuntimeError('Packet frame association missing or nonincreasing')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--phase-dir', type=Path, required=True)
    parser.add_argument('--scopes', default='execution,detector,diagnostic')
    parser.add_argument('--with-system', action='store_true', help='Camera free; robot stationary; stable scene; isolated ROS87')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    scopes = [x.strip() for x in args.scopes.split(',') if x.strip()]
    if not scopes or len(scopes) != len(set(scopes)):
        parser.error('Select nonempty unique scopes')
    if 'system' in scopes and not args.with_system and not args.dry_run:
        parser.error('Use --with-system only in a stationary safe camera test window')
    run, phase = args.run_dir.resolve(), args.phase_dir.resolve()
    if phase.parent != run or run.parent.name != 'E04_tensorrt_pipeline':
        raise ValueError('Independent E04 phase required')
    payload = read(phase / 'performance_manifest.json')
    fingerprint = digest(phase / 'performance_manifest.json')
    matrix = payload.get('matrix', 'single_components')
    specs = schedule(scopes, matrix)
    all_specs = schedule(matrix_scopes(matrix), matrix)
    if not specs:
        raise ValueError('No selected jobs')
    if payload.get('schedule_sha256') and hashlib.sha256(json.dumps(all_specs, sort_keys=True).encode()).hexdigest() != payload['schedule_sha256']:
        raise RuntimeError('Frozen performance schedule changed')
    correct = (run / payload['correctness_phase']).resolve()
    if correct.parent != run:
        raise ValueError('Correctness phase must belong to this run')
    correct_manifest = read(correct / 'phase_manifest.json')
    if digest(correct / 'phase_manifest.json') != payload['correctness_manifest_sha256']:
        raise RuntimeError('Correctness-tested source identity differs')
    complete = read(correct / 'CORRECTNESS_COLLECTION_COMPLETE.json')
    if complete['payload_sha256'] != payload['correctness_manifest_sha256'] or not all(v == 'passed' for v in complete['jobs'].values()):
        raise RuntimeError('Single-component correctness not completed')
    expected_gate = 'passed_for_combination_benchmark' if matrix == 'combined_pipeline' else 'passed_for_single_component_benchmark'
    gate = read(phase / 'correctness_gate.json')
    if gate['status'] != expected_gate:
        raise RuntimeError('Coordinator correctness gate missing')
    if matrix == 'combined_pipeline' and (gate.get('allowed_matrix') != matrix or
            set(gate.get('allowed_variants', [])) != {s['variant'] for s in all_specs}):
        raise RuntimeError('Combination gate does not approve this frozen matrix')
    sys.path.insert(0, str(run / 'scripts'))
    from stage0_robot import verify_sources, conflicting_processes, telemetry
    contract = read(run / 'frozen_contract.json')
    def verify():
        verify_sources(contract)
        for base, entries in [(phase, payload['files']), (correct, correct_manifest['files']), (run, payload['reference_files'])]:
            for item in entries:
                path = (base / item['path']).resolve()
                if base not in path.parents or digest(path) != item['sha256']:
                    raise RuntimeError('Frozen candidate/tool/reference changed: ' + str(path))
        versions = {name: importlib.metadata.version(name) for name in payload['distribution_versions']}
        if versions != payload['distribution_versions']:
            raise RuntimeError('Runtime distributions changed: ' + repr(versions))
        import cv2
        if cv2.__version__ != payload['opencv_version']:
            raise RuntimeError('OpenCV runtime changed since the exact correctness reference')
        from soccer_perception.ros.node import config_from_ros_params
        config = {k: str(v) if isinstance(v, Path) else v for k, v in vars(config_from_ros_params()).items()}
        if config != contract['parameters']:
            raise RuntimeError('Effective baseline configuration changed')
        power = subprocess.check_output(['nvpmodel', '-q'], stderr=subprocess.STDOUT, universal_newlines=True)
        if not re.search(r'NV Power Mode:\s*25W\b', power):
            raise RuntimeError('Power mode differs; no automatic adjustment')
        return power
    power = verify()
    if args.dry_run:
        print(json.dumps(dict(status='ready', gpu_work=False, camera_work=False, scopes=scopes,
                             jobs=len(specs), timed_minutes=len(specs), payload_sha256=fingerprint,
                             matrix=matrix, note='Additional startup/warmup. Performance collection only; no automatic adoption or stability approval.'), indent=2))
        return 0
    if os.environ.get('ROS_DOMAIN_ID') != '87' or os.environ.get('ROS_LOCALHOST_ONLY') != '1':
        raise RuntimeError('Use the isolated launcher')
    lock = (run.parent / 'gpu_benchmark.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    def conflicts():
        found = conflicting_processes()
        names = ['E04_ENGINE_GRAPH_BENCHMARK.py', 'candidate_entry.py', 'graph_probe.py',
                 'stage0_replay.py', 'stage0_robot.py', 'run_correctness_robot.py', 'run_performance_robot.py']
        for directory in Path('/proc').iterdir():
            if not directory.name.isdigit() or int(directory.name) == os.getpid(): continue
            try:
                arguments = (directory / 'cmdline').read_bytes().decode(errors='replace')
                if any(name in arguments for name in names): found.append(dict(pid=int(directory.name), reason='other E04 job'))
            except OSError: pass
        return found
    if conflicts():
        raise RuntimeError('Other benchmark/vision/test-domain task found; no process stopped')
    if list(phase.glob('INVALID_BASELINE_BLOCK_*.json')):
        raise RuntimeError('A drifting baseline invalidated a block; coordinator must review before a fresh phase. Do not delete this guard.')
    history = phase / 'performance_jobs.json'
    if history.exists() and not args.resume:
        raise FileExistsError('Earlier attempt exists; inspect and use explicit --resume')
    jobs = read(history) if history.exists() else []
    if any(x['payload_sha256'] != fingerprint for x in jobs):
        raise RuntimeError('Cannot resume with another payload')
    if args.resume and supersede_partial_blocks(jobs, all_specs, scopes):
        write(history, jobs)
    protected = read(run / 'protected_models_after.json')
    if any(digest(Path(p)) != h for p, h in protected.items()):
        raise RuntimeError('Protected original model changed')
    with (phase / 'power_performance.txt').open('a') as stream:
        stream.write(utc() + '\n' + power + '\n')
    write(phase / ('environment_' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'),
          dict(utc=utc(), python=sys.version, platform=platform.platform(), scopes=scopes,
               selected_environment={k: os.environ.get(k) for k in ['ROS_DOMAIN_ID', 'ROS_LOCALHOST_ONLY', 'RMW_IMPLEMENTATION', 'CUDA_LAUNCH_BLOCKING', 'OMP_NUM_THREADS']},
               versions=payload['distribution_versions']))
    done = threading.Event()
    monitor = threading.Thread(target=telemetry, args=(phase, done), daemon=True); monitor.start()
    scripts = phase / 'scripts'
    existing_worker = Path(payload['project']) / 'tool/model_benchmark/worker.py'
    info = payload['engine_info']
    model = dict(name='R0_E01', path=str(run / 'frozen_models/E01_baseline.engine'))

    def command(spec, output):
        if spec['scope'] == 'execution':
            return [sys.executable, '-u', str(scripts / 'E04_ENGINE_GRAPH_BENCHMARK.py'), '--run-dir', str(run),
                    '--output', str(output), '--variant', spec['variant'], '--warmup', '100', '--seconds', '60']
        config_path = phase / (output.name + '_variant.json')
        write(config_path, spec['switches'])
        base = [sys.executable, '-u', str(scripts / 'candidate_entry.py'), '--variant-json', str(config_path),
                '--status-file', str(output) + '_hooks.json']
        if spec['scope'] in ('detector', 'diagnostic'):
            return base + ['--entry', str(run / 'scripts/stage0_replay.py'), '--', '--run-dir', str(run),
                           '--output', str(output), '--mode', 'detector', '--warmup', '100', '--seconds', '60']
        output.mkdir(exist_ok=False)
        config = dict(test=dict(warmup_iterations=100, duration_seconds=60, input_shape=[2, 3, 640, 640]),
                      system=dict(publish_rate_hz=contract['parameters']['deploy_packet_rate_hz'],
                          viser_enabled=contract['parameters']['zed_viser_enabled'], point_cloud_enabled=False, parameter_overrides={}))
        job_path = phase / (output.name + '_worker.json')
        write(job_path, dict(directory=str(output), mode='system', model=model, config=config, info=info))
        return base + ['--entry', str(existing_worker), '--', str(job_path)]

    try:
        for spec in specs:
            if any(j['name'] == spec['name'] and j['status'] == 'complete' for j in jobs):
                print('[SKIP completed] ' + spec['name'], flush=True); continue
            verify()
            if conflicts():
                raise RuntimeError('Another GPU/vision job appeared; stop without terminating it')
            attempt = 1 + sum(j['name'] == spec['name'] for j in jobs)
            output = phase / (spec['name'] + '_attempt%d' % attempt)
            record = dict(spec, attempt=attempt, status='running', started_utc=utc(), output=str(output), payload_sha256=fingerprint)
            processes = []
            for directory in Path('/proc').iterdir():
                if not directory.name.isdigit(): continue
                try:
                    if directory.stat().st_uid == os.getuid():
                        processes.append(dict(pid=int(directory.name), name=(directory / 'comm').read_text().strip()))
                except OSError: pass
            record['background_start'] = dict(loadavg=list(os.getloadavg()), user_processes=processes)
            jobs.append(record); write(history, jobs)
            print('[RUN] ' + spec['name'] + ' -> ' + str(output), flush=True)
            try:
                cmd = command(spec, output); record['command'] = cmd; write(history, jobs)
                with (phase / (output.name + '.log')).open('x') as log:
                    def started(pid):
                        record['worker_pid'] = pid; write(history, jobs)
                    code = run_child(cmd, log, lock.fileno(), started, timeout_seconds=240)
                record['returncode'] = code
                if code:
                    raise RuntimeError('Worker failed; inspect retained log')
                result = read(output / 'result.json')
                if spec['scope'] == 'execution':
                    if result['status'] != 'complete_pending_coordinator_review' or not result['formal_100_warmup_60_seconds'] or result['measured_loop_seconds'] < 60 or result.get('restore') != 'complete':
                        raise RuntimeError('Execution worker did not complete formal boundary')
                    samples = result['samples']
                else:
                    if result['status'] != 'complete': raise RuntimeError('Measurement incomplete')
                    metrics = summarize(output / 'frames.csv', spec['scope'])
                    samples = next(v['n'] for k, v in metrics.items() if k.endswith('_ms'))
                    hook = validate_hooks(Path(str(output) + '_hooks.json'), spec, samples, payload['expected_runtime'])
                    if spec['scope'] == 'system':
                        progress = read(output / 'progress.json')
                        if progress['warmup_total'] != 100 or progress['elapsed'] < 60 or progress['completed'] != samples:
                            raise RuntimeError('System warmup/duration/count mismatch')
                        if payload.get('packet_observation'):
                            validate_packet_observation(hook, metrics, samples)
                    else:
                        runtime = read(output / 'effective_runtime.json')
                        if runtime['warmup_excluded'] != 100 or result['seconds'] != 60 or result['samples'] != samples:
                            raise RuntimeError('Replay warmup/duration/count mismatch')
                    if 'measurement_only_c1_timings' in hook:
                        record['c1_segments'] = hook['measurement_only_c1_timings']
                metrics = summarize(output / 'frames.csv', spec['scope'])
                if any(v['n'] != samples for k, v in metrics.items() if k.endswith('_ms')):
                    raise RuntimeError('Raw CSV row count differs from worker result')
                files = [p for p in output.rglob('*') if p.is_file()]
                files += [p for p in phase.glob(output.name + '*') if p.is_file()]
                artifacts = [dict(path=str(p.relative_to(phase)), bytes=p.stat().st_size, sha256=digest(p)) for p in files]
                record.update(status='complete', samples=samples, metrics=metrics, completed_utc=utc(), artifacts=artifacts)
                write(history, jobs)
                print('[DONE] ' + spec['name'] + ' samples=' + str(samples), flush=True)
                if is_baseline_end(spec, specs):
                    start_name = '%s_r%d_00_R0' % (spec['scope'], spec['round'])
                    before = next(j for j in reversed(jobs) if j['name'] == start_name and j['status'] == 'complete')
                    key = 'detector_wall_ms' if spec['scope'] == 'detector' else 'read_ready_to_publish_ms'
                    drift = abs(record['metrics'][key]['mean'] / before['metrics'][key]['mean'] - 1) * 100
                    record['bracket_baseline_drift_percent'] = drift; write(history, jobs)
                    if drift > 3:
                        marker = phase / ('INVALID_BASELINE_BLOCK_%s_r%d.json' % (spec['scope'], spec['round']))
                        write(marker, dict(reason='R0 bracket drift >3%', drift_percent=drift, utc=utc(),
                              scope=spec['scope'], round=spec['round'], payload_sha256=fingerprint,
                              action='Whole block excluded; automatic resume prohibited; retain all raw data'))
                        for job in jobs:
                            if job['scope'] == spec['scope'] and job.get('round') == spec['round']:
                                job.update(prior_status=job['status'], status='invalid_baseline_drift', invalidated_utc=utc())
                        write(history, jobs)
                        raise RuntimeError('R0 bracket drift >3%; stop and review environment/scene before further collection')
            except BaseException as error:
                record.update(status='failed_requires_review', error=repr(error), completed_utc=utc())
                write(history, jobs)
                raise
        verify()
        if any(digest(Path(p)) != h for p, h in protected.items()):
            raise RuntimeError('Original model integrity failed after measurement')
        complete_names = {j['name'] for j in jobs if j['status'] == 'complete'}
        full = all(j['name'] in complete_names for j in all_specs)
        status = dict(status='collected_pending_coordinator_review', completed_utc=utc(), scopes=scopes,
                      matrix=matrix, full_requested_matrix_collected=full,
                      full_single_component_matrix_collected=full and matrix=='single_components', payload_sha256=fingerprint,
                      production_changed=False, stability_approved=False, combinations_A_B_tested=matrix=='combined_pipeline',
                      note='Individual performance requires repeatability, tail-latency and scene review. No automatic adoption.')
        marker = 'PERFORMANCE_COLLECTION_COMPLETE.json' if full else 'PERFORMANCE_PARTIAL_' + '_'.join(scopes) + '.json'
        write(phase / marker, status)
        print(json.dumps(status, indent=2), flush=True)
    except BaseException as error:
        write(phase / ('PERFORMANCE_FAILURE_' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'),
              dict(status='failed_requires_review', error=repr(error), utc=utc(), payload_sha256=fingerprint))
        raise
    finally:
        done.set(); monitor.join(timeout=3); lock.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
