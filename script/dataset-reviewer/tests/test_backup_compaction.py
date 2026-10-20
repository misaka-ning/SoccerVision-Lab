import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'maintenance/compact_metadata_backups.py'
SPEC = importlib.util.spec_from_file_location('compact_metadata_backups', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@unittest.skipUnless(shutil.which('zstd'), 'zstd is required for archive tests')
class BackupCompactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.dataset = root/'datasets'
        self.backups = self.dataset/'.metadata-review-backups'
        self.backups.mkdir(parents=True)
        self.originals = {}
        for i in range(5):
            path = self.backups/f'metadata-20261019-{i:02d}.csv'
            data = ('图片,备注\r\n样本,保留历史记录%d\r\n' % i).encode('utf-8-sig') * 100
            path.write_bytes(data)
            self.originals[path.name] = data
        self.archive = root/'archives/old-backups'
        self.metadata = self.dataset/'metadata.csv'
        self.metadata.write_bytes(b'live-metadata-untouched')

    def test_dry_run_writes_nothing(self):
        result = MODULE.compact(self.dataset, self.archive, keep=2)
        self.assertEqual(result['old_backups'], 3)
        self.assertFalse(self.archive.exists())
        self.assertEqual(len(list(self.backups.iterdir())), 5)

    def test_verified_archive_preserves_all_old_bytes_and_keeps_recent(self):
        result = MODULE.compact(self.dataset, self.archive, keep=2, apply=True)
        self.assertEqual(result['sha256_verified_files'], 3)
        self.assertEqual(result['removed_loose_files'], 3)
        entries = json.loads((self.archive/'manifest.json').read_text())
        MODULE.verify_archive(Path(result['archive']), entries, shutil.which('zstd'))
        self.assertEqual({p.name for p in self.backups.iterdir()}, set(self.originals)-{r['name'] for r in entries})
        self.assertEqual(self.metadata.read_bytes(), b'live-metadata-untouched')

    def test_archive_verification_failure_never_removes_source(self):
        with patch.object(MODULE, 'verify_archive', side_effect=ValueError('checksum mismatch')):
            with self.assertRaises(ValueError):
                MODULE.compact(self.dataset, self.archive, keep=2, apply=True)
        self.assertEqual({p.name:p.read_bytes() for p in self.backups.iterdir()}, self.originals)

    def test_source_edit_after_verification_prevents_any_removal(self):
        real_verify = MODULE.verify_archive
        def edit_source(path, entries, zstd):
            real_verify(path, entries, zstd)
            (self.backups/entries[0]['name']).write_bytes(b'newer-user-backup')
        with patch.object(MODULE, 'verify_archive', side_effect=edit_source):
            with self.assertRaises(RuntimeError):
                MODULE.compact(self.dataset, self.archive, keep=2, apply=True)
        self.assertEqual(len(list(self.backups.iterdir())), 5)
        self.assertEqual(self.metadata.read_bytes(), b'live-metadata-untouched')


if __name__ == '__main__':
    unittest.main()
