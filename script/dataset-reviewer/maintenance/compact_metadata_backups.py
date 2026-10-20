#!/usr/bin/env python3
"""Losslessly archive old GUI metadata backups, retaining recent loose copies.

Dry-run by default. --apply streams a single-threaded zstd tar archive, verifies
every member against its original SHA256, then removes only unchanged old CSVs.
The live metadata, images, labels, and label-edit backups are never modified.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile


class HashingReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, size=-1):
        data = self.stream.read(size)
        self.digest.update(data)
        return data


def snapshot(path):
    s = path.stat()
    return dict(size=s.st_size, mtime_ns=s.st_mtime_ns, inode=s.st_ino)


def verify_archive(path, entries, zstd):
    expected = {'metadata-backups/' + r['name']: r for r in entries}
    seen = set()
    process = subprocess.Popen([zstd, '-q', '-d', '-c', '--long=25', str(path)],
                               stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
            for member in archive:
                if not member.isfile() or member.name in seen:
                    raise ValueError('Unexpected or duplicate archive member: ' + member.name)
                seen.add(member.name)
                stream = archive.extractfile(member)
                if member.name == 'manifest.json':
                    if json.load(stream) != entries:
                        raise ValueError('Archive manifest mismatch')
                    continue
                row = expected[member.name]
                digest = hashlib.sha256()
                for data in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(data)
                if member.size != row['size'] or digest.hexdigest() != row['sha256']:
                    raise ValueError('Archive verification failed: ' + member.name)
        for _ in iter(lambda: process.stdout.read(1024 * 1024), b''):
            pass
        if process.wait() != 0 or seen != set(expected) | {'manifest.json'}:
            raise ValueError('Archive is incomplete or decompression failed')
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.kill()
            process.wait()


def compact(dataset, archive_dir, *, keep=10, apply=False):
    if keep < 1:
        raise ValueError('At least one recent loose backup must be retained')
    dataset = dataset.resolve()
    backup_dir = dataset / '.metadata-review-backups'
    if backup_dir.is_symlink() or not backup_dir.is_dir():
        raise ValueError('Expected a regular metadata backup directory')
    files = sorted(backup_dir.glob('metadata-*.csv'), key=lambda p: (p.stat().st_mtime_ns, p.name))
    if any(p.is_symlink() or not p.is_file() for p in files):
        raise ValueError('Symlink or non-file backup refused')
    chosen = files[:-keep]
    entries = [dict(name=p.name, **snapshot(p)) for p in chosen]
    result = dict(old_backups=len(chosen), kept_loose=min(keep, len(files)),
                  original_bytes=sum(r['size'] for r in entries),
                  dry_run=not apply, live_dataset_written=False)
    if not apply or not chosen:
        return result
    zstd = shutil.which('zstd')
    if not zstd:
        raise RuntimeError('zstd is required before any backup can be removed')
    archive_dir = archive_dir.absolute()
    if archive_dir == dataset or dataset in archive_dir.parents:
        raise ValueError('Archive must be outside the live dataset')
    archive_dir.mkdir(parents=True, exist_ok=False)
    partial = archive_dir / 'metadata-backups.tar.zst.partial'
    archive_path = archive_dir / 'metadata-backups.tar.zst'
    process = subprocess.Popen([zstd, '-q', '--check', '-1', '--long=25', '-T1',
                                '-o', str(partial)], stdin=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdin, mode='w|') as archive:
            for i, (path, row) in enumerate(zip(chosen, entries), 1):
                if snapshot(path) != {k: row[k] for k in ('size', 'mtime_ns', 'inode')}:
                    raise RuntimeError('Backup changed before archiving: ' + path.name)
                info = archive.gettarinfo(str(path), arcname='metadata-backups/' + path.name)
                with path.open('rb') as stream:
                    reader = HashingReader(stream)
                    archive.addfile(info, reader)
                    row['sha256'] = reader.digest.hexdigest()
                if snapshot(path) != {k: row[k] for k in ('size', 'mtime_ns', 'inode')}:
                    raise RuntimeError('Backup changed during archiving: ' + path.name)
                if i % 500 == 0:
                    print(f'Archived {i}/{len(chosen)} backups', flush=True)
            data = (json.dumps(entries, ensure_ascii=False, indent=2) + '\n').encode()
            info = tarfile.TarInfo('manifest.json')
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError('Backup compression failed; no original was removed')
    finally:
        if process.poll() is None:
            process.stdin.close()
            process.kill()
            process.wait()
    verify_archive(partial, entries, zstd)
    # Validate the complete removal set before deleting even one source file.
    for path, row in zip(chosen, entries):
        if snapshot(path) != {k: row[k] for k in ('size', 'mtime_ns', 'inode')}:
            raise RuntimeError('Backup changed after archiving; originals retained: ' + path.name)
    partial.rename(archive_path)
    (archive_dir/'manifest.json').write_text(json.dumps(entries, ensure_ascii=False, indent=2) + '\n')
    result.update(archive=str(archive_path), archive_bytes=archive_path.stat().st_size,
                  sha256_verified_files=len(entries), removed_loose_files=0,
                  created_at_utc=datetime.now(timezone.utc).isoformat())
    result_path = archive_dir/'result.json'
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    try:
        for path, row in zip(chosen, entries):
            if snapshot(path) != {k: row[k] for k in ('size', 'mtime_ns', 'inode')}:
                raise RuntimeError('Backup changed during removal; verified archive retained')
            path.unlink()
            result['removed_loose_files'] += 1
    finally:
        result['net_bytes_released'] = sum(r['size'] for r in entries[:result['removed_loose_files']]) - result['archive_bytes']
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, help='显式覆盖数据集；默认script/config.yaml')
    parser.add_argument('--archive-dir', required=True, type=Path)
    parser.add_argument('--keep', type=int, default=10)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.dataset is None:
        from review_paths import current_dataset
        args.dataset = current_dataset()
    print(json.dumps(compact(args.dataset, args.archive_dir, keep=args.keep, apply=args.apply),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
