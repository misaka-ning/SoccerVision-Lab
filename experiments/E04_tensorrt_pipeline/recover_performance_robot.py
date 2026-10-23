#!/usr/bin/env python3
"""CPU-only snapshot of completed E04 performance evidence; no worker is run."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import tarfile


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(part)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase-dir', type=Path, required=True)
    parser.add_argument('--label', default='offline_recovery_v1')
    args = parser.parse_args()
    phase = args.phase_dir.resolve()
    run = phase.parent
    if not args.label.replace('_', '').isalnum():
        raise ValueError('Simple unique label required')
    archive = phase / (args.label + '.tar.gz')
    if archive.exists():
        raise FileExistsError(archive)
    payload = json.loads((phase / 'performance_manifest.json').read_text())
    contract = json.loads((run / 'frozen_contract.json').read_text())
    correct = run / payload['correctness_phase']
    tested = json.loads((correct / 'phase_manifest.json').read_text())
    errors, counts = [], {}
    groups = [('deployed_sources', [(Path(i['path']), i['sha256']) for i in contract['sources']]),
              ('protected_models', [(Path(p), h) for p, h in json.loads((run / 'protected_models_after.json').read_text()).items()]),
              ('candidate_payload', [(correct / i['path'], i['sha256']) for i in tested['files']]),
              ('performance_payload', [(phase / i['path'], i['sha256']) for i in payload['files']]),
              ('references', [(run / i['path'], i['sha256']) for i in payload['reference_files']])]
    for name, entries in groups:
        counts[name] = len(entries)
        for path, expected in entries:
            if not path.is_file() or sha(path) != expected:
                errors.append(dict(group=name, path=str(path)))
    jobs = json.loads((phase / 'performance_jobs.json').read_text())
    artifact_count = 0
    for job in jobs:
        for item in job.get('artifacts', []):
            path = phase / item['path']
            artifact_count += 1
            if not path.is_file() or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
                errors.append(dict(group='job_artifact', path=str(path)))
    counts['job_artifacts'] = artifact_count
    evidence = dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    counts=counts, errors=errors, jobs=len(jobs),
                    performance_manifest_sha256=sha(phase / 'performance_manifest.json'),
                    correctness_manifest_sha256=sha(correct / 'phase_manifest.json'),
                    engine_sha256=sha(run / 'frozen_models/E01_baseline.engine'),
                    gpu_work=False, production_changed=False)
    integrity = phase / (args.label + '_integrity.json')
    integrity.write_text(json.dumps(evidence, indent=2) + '\n')
    if errors:
        raise RuntimeError('Integrity mismatch; see ' + str(integrity))
    excluded = {'source', 'scripts', '__pycache__'}
    files = [p for p in phase.rglob('*') if p.is_file()
             and not any(x in excluded for x in p.relative_to(phase).parts)
             and not p.name.endswith(('.tar.gz', '.pyc'))
             and not any(x.startswith('recovered') for x in p.relative_to(phase).parts)]
    manifest = phase / (args.label + '_manifest.json')
    if manifest.exists():
        raise FileExistsError(manifest)
    entries = [dict(path=str(p.relative_to(phase)), bytes=p.stat().st_size, sha256=sha(p)) for p in sorted(files)]
    manifest.write_text(json.dumps(dict(files=entries, phase_id=phase.name), indent=2) + '\n')
    with tarfile.open(str(archive), 'w:gz') as target:
        for path in sorted(files) + [manifest]:
            target.add(str(path), arcname=str(path.relative_to(phase)), recursive=False)
    print(json.dumps(dict(archive=str(archive), bytes=archive.stat().st_size,
                         sha256=sha(archive), files=len(entries) + 1, integrity=evidence), indent=2))


if __name__ == '__main__':
    main()
