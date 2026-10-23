#!/usr/bin/env python3
"""Short interface smoke only; never enters the formal measurement history."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

from performance_runner import run_child


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase-dir', type=Path, required=True)
    args = parser.parse_args()
    phase = args.phase_dir.resolve(); run = phase.parent; scripts = phase / 'scripts'
    subprocess.check_call(['bash', str(scripts / 'run_performance.sh'), '--dry-run'])
    sys.path.insert(0, str(run / 'scripts'))
    from stage0_robot import conflicting_processes
    lock = (run.parent / 'gpu_benchmark.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if conflicting_processes(): raise RuntimeError('Other vision/GPU task detected; no task stopped')
    names = ['candidate_entry.py', 'E04_ENGINE_GRAPH_BENCHMARK.py', 'run_correctness_robot.py', 'run_performance_robot.py']
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit() or int(directory.name) == os.getpid(): continue
        try:
            value = (directory / 'cmdline').read_bytes().decode(errors='replace')
            if any(name in value for name in names): raise RuntimeError('Other E04 task found; no task stopped')
        except OSError: pass
    output = phase / 'smoke_short'
    output.mkdir(exist_ok=False)
    variant = output / 'r0.json'; variant.write_text('{}\n')
    commands = [[sys.executable, str(scripts / 'E04_ENGINE_GRAPH_BENCHMARK.py'), '--run-dir', str(run),
                 '--output', str(output / key), '--variant', key, '--warmup', '1', '--seconds', '0.1'] for key in ['b0', 'graph']]
    commands.append([sys.executable, str(scripts / 'candidate_entry.py'), '--entry', str(run / 'scripts/stage0_replay.py'),
                     '--variant-json', str(variant), '--status-file', str(output / 'r0_hooks.json'), '--', '--run-dir', str(run),
                     '--output', str(output / 'detector'), '--mode', 'detector', '--warmup', '1', '--seconds', '0.1'])
    for index, command in enumerate(commands):
        with (output / ('job%d.log' % index)).open('x') as stream:
            code = run_child(command, stream, lock.fileno(), lambda pid: None, timeout_seconds=90)
        if code: raise RuntimeError('Smoke job failed: ' + str(index))
    expected = json.loads((phase / 'performance_manifest.json').read_text())['expected_runtime']
    hooks = json.loads((output / 'r0_hooks.json').read_text())
    if hooks['validation_errors'] or hooks['runtime_identity'] != [expected]: raise RuntimeError('Runtime checkpoint identity differs')
    result = dict(status='interface_smoke_passed', warmup=1, seconds=0.1, formal_performance=False,
                  execution_variants=['b0', 'graph'], detector_hook_checkpoint=True, camera_or_ros_used=False)
    (output / 'SMOKE_COMPLETE.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__': main()
