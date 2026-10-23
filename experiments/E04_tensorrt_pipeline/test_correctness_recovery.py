import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from recover_correctness_robot import main


class RecoveryTests(unittest.TestCase):
    def fixture(self, root):
        phase = root / 'phase'
        phase.mkdir()
        reference = root / 'stage0_golden_attempt1'
        reference.mkdir()
        for name, data in [('same.npz', b'identical bytes'), ('different.npz', b'baseline')]:
            (reference / name).write_bytes(data)
        output = phase / 'R0_attempt1'
        output.mkdir()
        (output / 'same.npz').write_bytes(b'identical bytes')
        (output / 'different.npz').write_bytes(b'candidate differs')
        source = root / 'production.py'
        source.write_text('frozen source')
        models = root / 'frozen_models'
        models.mkdir()
        engine = models / 'E01_baseline.engine'
        engine.write_bytes(b'protected model')
        digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        (root / 'frozen_contract.json').write_text(json.dumps({'sources': [{'path': str(source), 'sha256': digest(source)}]}))
        (root / 'protected_models_after.json').write_text(json.dumps({str(engine): digest(engine)}))
        (phase / 'phase_manifest.json').write_text(json.dumps({'files': []}))
        return phase, source

    def test_only_identical_full_files_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            phase, _ = self.fixture(Path(directory))
            with patch.object(sys, 'argv', ['recover', '--phase-dir', str(phase)]), patch('sys.stdout', io.StringIO()):
                main()
            manifest = json.loads((phase / 'correctness_recovery_v1_manifest.json').read_text())
            same = next(i for i in manifest['files'] if i['path'].endswith('/same.npz'))
            different = next(i for i in manifest['files'] if i['path'].endswith('/different.npz'))
            self.assertEqual(same['reference_path'], 'stage0_golden_attempt1/same.npz')
            self.assertNotIn('reference_path', different)
            with tarfile.open(phase / 'correctness_recovery_v1.tar.gz') as archive:
                self.assertNotIn(same['path'], archive.getnames())
                self.assertEqual(archive.extractfile(different['path']).read(), b'candidate differs')

    def test_source_drift_stops_before_archive_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            phase, source = self.fixture(Path(directory))
            source.write_text('modified')
            with patch.object(sys, 'argv', ['recover', '--phase-dir', str(phase)]):
                with self.assertRaises(RuntimeError):
                    main()
            self.assertFalse((phase / 'correctness_recovery_v1.tar.gz').exists())
            integrity = json.loads((phase / 'correctness_recovery_v1_integrity.json').read_text())
            self.assertEqual(integrity['errors'][0]['group'], 'deployed_sources')


if __name__ == '__main__':
    unittest.main()
