#!/usr/bin/env python3
"""Copy legacy install models to the shared directory without overwriting anything."""
import argparse
import hashlib
import shutil
from pathlib import Path


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.digest()


def migrate(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_dir() or source == destination:
        return []
    files = sorted(path for path in source.rglob('*') if path.is_file()
                   and (path.suffix in {'.pt', '.onnx', '.engine'} or path.name.endswith('.engine.json')))
    # Preflight every conflict before copying any file.
    for path in files:
        target = destination / path.relative_to(source)
        if target.exists() and (not target.is_file() or digest(path) != digest(target)):
            raise RuntimeError(f'Model migration conflict: {path} != {target}. '
                               'Choose which version to keep; no files were overwritten.')
    copied = []
    for path in files:
        target = destination / path.relative_to(source)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with path.open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst)
        copied.append(target)
        print(f'Preserved model: {path} -> {target}')
    return copied


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    migrate(args.source, args.destination)
