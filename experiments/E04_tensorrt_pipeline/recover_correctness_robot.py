#!/usr/bin/env python3
"""CPU-only, hash-preserving recovery of E04 Golden collection evidence."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import tarfile


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(data)
    return value.hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase-dir', type=Path, required=True)
    parser.add_argument('--label', default='correctness_recovery_v1')
    args = parser.parse_args()
    if not args.label.replace('_', '').isalnum():
        raise ValueError('Simple unique label required')
    phase = args.phase_dir.resolve()
    run = phase.parent
    archive = phase / (args.label + '.tar.gz')
    manifest_path = phase / (args.label + '_manifest.json')
    if archive.exists() or manifest_path.exists():
        raise FileExistsError('Keep previous recovery, use a new label')
    payload = read(phase / 'phase_manifest.json')
    contract = read(run / 'frozen_contract.json')
    groups = [('deployed_sources', [(Path(i['path']), i['sha256']) for i in contract['sources']]),
              ('protected_models', [(Path(p), h) for p, h in read(run / 'protected_models_after.json').items()]),
              ('candidate_payload', [(phase / i['path'], i['sha256']) for i in payload['files']]),
              ('references', [(run / i['path'], i['sha256']) for i in payload.get('reference_files', [])])]
    errors, counts = [], {}
    for group, entries in groups:
        counts[group] = len(entries)
        for path, expected in entries:
            if not path.is_file() or sha(path) != expected:
                errors.append(dict(group=group, path=str(path)))
    integrity = dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), counts=counts,
                     errors=errors, phase_manifest_sha256=sha(phase / 'phase_manifest.json'),
                     engine_sha256=sha(run / 'frozen_models/E01_baseline.engine'),
                     gpu_work=False, camera_work=False)
    integrity_path = phase / (args.label + '_integrity.json')
    integrity_path.write_text(json.dumps(integrity, indent=2) + '\n')
    if errors:
        raise RuntimeError('Integrity mismatch, see ' + str(integrity_path))
    files = [p for p in phase.rglob('*') if p.is_file()
             and not any(s in {'scripts', 'source', '__pycache__'} or s.startswith('recovered') for s in p.relative_to(phase).parts)
             and not p.name.endswith(('.tar.gz', '.pyc'))]
    entries, stored, referenced = [], [], 0
    for path in sorted(files):
        entry = dict(path=str(path.relative_to(phase)), bytes=path.stat().st_size, sha256=sha(path))
        reference = run / 'stage0_golden_attempt1' / path.name
        if path.suffix == '.npz' and reference.is_file() and sha(reference) == entry['sha256']:
            entry['reference_path'] = str(reference.relative_to(run))
            referenced += 1
        else:
            stored.append(path)
        entries.append(entry)
    manifest_path.write_text(json.dumps(dict(phase_id=phase.name, files=entries,
                                             referenced_npz=referenced, deduplication='Only full-file SHA256-identical baseline NPZ'), indent=2) + '\n')
    with tarfile.open(str(archive), 'w:gz') as output:
        for path in stored + [manifest_path]:
            output.add(str(path), arcname=str(path.relative_to(phase)), recursive=False)
    print(json.dumps(dict(archive=str(archive), bytes=archive.stat().st_size, sha256=sha(archive),
                          files=len(entries) + 1, referenced_npz=referenced, integrity=integrity), indent=2))


if __name__ == '__main__':
    main()
