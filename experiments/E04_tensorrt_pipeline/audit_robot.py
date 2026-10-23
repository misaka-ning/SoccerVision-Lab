#!/usr/bin/env python3
"""Short CPU-only E04-0 audit; creates only a new E04 result directory.

Use the existing deployment Python environment. No inference, camera/ROS node,
package installation, model export, process termination or clock writes.
"""
import argparse
import datetime
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys


EXPECTED_E01 = '98c1b6bc703b29874d95db94d9cf51ef5b4a4142a7ca6cf22362a0c616fbf348'
PRUNE = {'results', '.git', '__pycache__', 'build', 'log', 'datasets', 'data', 'node_modules', '.venv'}
SOURCE_SUFFIXES = {'.py', '.sh', '.yaml', '.yml', '.msg', '.srv', '.idl', '.xml', '.cfg', '.toml', '.txt'}
SECRET = re.compile(r'''(?im)^(\s*["']?(?:password|passwd|token|api[_-]?key|secret)["']?\s*[:=]\s*)([^\r\n]+)''')


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def new_output(project, output):
    project = Path(project).resolve()
    base = (project / 'results/E04_tensorrt_pipeline').resolve()
    output = Path(output).resolve()
    if not project.is_dir() or base not in output.parents:
        raise ValueError('Output must be a new child of project/results/E04_tensorrt_pipeline')
    output.mkdir(parents=True, exist_ok=False)
    return output


def command(args, cwd=None):
    try:
        result = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, timeout=20)
        return dict(argv=args, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(argv=args, returncode=None, error=type(exc).__name__ + ': ' + str(exc))


def read_text(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def engine_metadata(path):
    """Inspect the optional Ultralytics header without deserializing TensorRT."""
    with Path(path).open('rb') as stream:
        first = stream.read(4)
        if len(first) != 4:
            return dict(format='too_short', metadata=None)
        length = struct.unpack('<I', first)[0]
        if not 0 < length <= 1024 * 1024 or length + 4 >= Path(path).stat().st_size:
            return dict(format='raw_or_unknown', metadata=None)
        try:
            data = json.loads(stream.read(length).decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            return dict(format='raw_or_unknown', metadata=None)
        return dict(format='ultralytics_header', header_bytes=length + 4, metadata=data)


def package_roots():
    result = {}
    for name in ['soccer_perception', 'ultralytics', 'torch', 'torchvision', 'tensorrt']:
        try:
            spec = importlib.util.find_spec(name)
            locations = list(spec.submodule_search_locations or []) if spec else []
            try:
                version = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                version = None
            result[name] = dict(origin=spec.origin if spec else None, roots=locations, distribution_version=version)
        except (ImportError, ValueError, AttributeError) as exc:
            result[name] = dict(error=str(exc), roots=[])
    return result


def project_files(project):
    """Enumerate deployment source, without scanning historical runs or Test data."""
    count = 0
    for current, dirs, files in os.walk(str(project), followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in PRUNE and d != 'install' and not d.startswith('.'))
        for name in sorted(files):
            count += 1
            if count > 30000:
                raise RuntimeError('Source enumeration exceeded 30000 entries; narrow source roots before retry')
            path = Path(current) / name
            if path.suffix in SOURCE_SUFFIXES or path.suffix == '.engine':
                yield path


def snapshot_file(path, target, records):
    """Keep credentials out of snapshots; mark any redaction for later review."""
    if path.stat().st_size > 2 * 1024 * 1024:
        records.append(dict(path=str(path), skipped='source exceeds 2 MiB', sha256=sha256(path)))
        return
    text = path.read_text(encoding='utf-8')
    cleaned, changes = SECRET.subn(r'\1"<REDACTED>"', text)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(cleaned, encoding='utf-8')
    records.append(dict(path=str(path), snapshot=str(target), original_sha256=sha256(path),
                        snapshot_sha256=sha256(target), redacted_lines=changes))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve()
    output = new_output(project, args.output)
    write_json(output / 'status.json', dict(status='running', started_utc=utc(), gpu_work=False))
    try:
        packages = package_roots()
        write_json(output / 'python_environment.json', dict(executable=sys.executable, version=sys.version,
                    platform=platform.platform(), packages=packages,
                    selected_environment={k: os.environ.get(k) for k in ['PYTHONPATH', 'ROS_DISTRO', 'ROS_DOMAIN_ID',
                        'RMW_IMPLEMENTATION', 'CUDA_LAUNCH_BLOCKING', 'CUDA_MODULE_LOADING', 'OMP_NUM_THREADS']}))
        checks = {
            'git_head': command(['git', 'rev-parse', 'HEAD'], str(project)),
            'git_status': command(['git', 'status', '--short'], str(project)),
            'power': command(['nvpmodel', '-q']),
            'memory': command(['free', '-m']),
            'storage': command(['df', '-h', str(project)]),
            'processes': command(['ps', '-eo', 'pid,ppid,comm']),
            'network_listeners': command(['ss', '-ltnp']),
        }
        write_json(output / 'system_commands.json', checks)
        gpu = Path('/sys/devices/17000000.ga10b')
        write_json(output / 'device_snapshot.json', dict(utc=utc(), loadavg=os.getloadavg(),
                    gpu={key: read_text(gpu / ('devfreq/17000000.ga10b/' + key)) for key in
                         ['cur_freq', 'min_freq', 'max_freq', 'available_frequencies']},
                    gpu_load_per_mille=read_text(gpu / 'load'),
                    thermal=[dict(zone=str(p), type=read_text(p / 'type'), value=read_text(p / 'temp'))
                             for p in sorted(Path('/sys/class/thermal').glob('thermal_zone*'))]))
        files = list(project_files(project))
        records = []
        for path in files:
            if path.suffix != '.engine':
                snapshot_file(path, output / 'source/project' / path.relative_to(project), records)
        # Installed Python roots are authoritative; keep them distinct from source checkout.
        selected = {
            'soccer_perception': None,
            'ultralytics': ['nn/autobackend.py', 'engine/predictor.py', 'engine/results.py',
                            'models/yolo/detect/predict.py', 'utils/ops.py', 'utils/nms.py', 'data/augment.py'],
            'torchvision': ['extension.py', 'ops/boxes.py', 'version.py'],
        }
        for name, subset in selected.items():
            for index, location in enumerate(packages.get(name, {}).get('roots', [])):
                base = Path(location)
                paths = sorted(base.rglob('*.py')) if subset is None else [base / p for p in subset]
                for path in paths:
                    if path.is_file():
                        snapshot_file(path, output / 'source/installed' / (name + '_' + str(index)) / path.relative_to(base), records)
        write_json(output / 'source_manifest.json', records)
        candidates = {str(p) for p in files if p.suffix == '.engine'}
        # Include share-model paths skipped with the install tree.
        for p in (project / 'install').glob('*/share/*/models/*.engine'):
            candidates.add(str(p))
        models = []
        for name in sorted(candidates):
            p = Path(name)
            if not p.is_file():
                continue
            digest = sha256(p)
            models.append(dict(path=name, resolved=str(p.resolve()), bytes=p.stat().st_size,
                               sha256=digest, is_frozen_E03_E01=digest == EXPECTED_E01, **engine_metadata(p)))
        write_json(output / 'engine_inventory.json', models)
        result = dict(status='collected_requires_review', completed_utc=utc(), gpu_work=False,
                      engine_identity_candidates=sum(x['is_frozen_E03_E01'] for x in models),
                      actual_loaded_engine_path=None, bindings_not_queried=True,
                      golden_reference='not_generated', performance='not_run',
                      stage0_gate='not_passed', source_records=len(records),
                      note='Coordinator must inspect actual configuration/call path and resolve differences before baseline/optimization.')
        write_json(output / 'status.json', result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        write_json(output / 'status.json', dict(status='failed', utc=utc(), error=repr(exc), gpu_work=False))
        raise


if __name__ == '__main__':
    main()
