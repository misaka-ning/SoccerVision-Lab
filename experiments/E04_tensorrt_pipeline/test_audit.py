import json
from pathlib import Path
import struct
import tempfile
import unittest

import audit_robot as audit


class AuditTests(unittest.TestCase):
    def test_existing_and_protected_outputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            output = project / 'results/E04_tensorrt_pipeline/run/audit'
            self.assertEqual(audit.new_output(project, output), output)
            with self.assertRaises(FileExistsError):
                audit.new_output(project, output)
            for path in [project / 'models/x', project / 'results/E03_tensorrt_profiling/x',
                         project / 'results/E04_tensorrt_pipeline']:
                with self.assertRaises(ValueError):
                    audit.new_output(project, path)

    def test_metadata_header_and_raw_engine_are_distinguished(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'engine'
            body = json.dumps({'batch': 2, 'args': {'nms': False}}).encode()
            path.write_bytes(struct.pack('<I', len(body)) + body + b'raw-plan')
            result = audit.engine_metadata(path)
            self.assertEqual(result['metadata']['batch'], 2)
            self.assertFalse(result['metadata']['args']['nms'])
            self.assertEqual(result['header_bytes'], len(body) + 4)
            path.write_bytes(b'not-a-metadata-header')
            self.assertEqual(audit.engine_metadata(path)['format'], 'raw_or_unknown')
            path.write_bytes(b'xx')
            self.assertEqual(audit.engine_metadata(path)['format'], 'too_short')

    def test_historical_runs_and_data_are_not_enumerated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['results/E03/x.py', 'data/test/x.py', '.git/config.py',
                         'build/old.py', 'install/source.py', 'pkg/current.py', 'pkg/CMakeLists.txt']:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('')
            found = {str(p.relative_to(root)) for p in audit.project_files(root)}
            self.assertEqual(found, {'pkg/current.py', 'pkg/CMakeLists.txt'})

    def test_credential_fields_are_redacted_and_original_fingerprint_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'config.yaml'
            source.write_text('conf: 0.45\npassword: private-example\ntoken: private-token\n')
            records = []
            target = root / 'snapshot/config.yaml'
            audit.snapshot_file(source, target, records)
            self.assertNotIn('private-example', target.read_text())
            self.assertNotIn('private-token', target.read_text())
            self.assertIn('conf: 0.45', target.read_text())
            self.assertEqual(records[0]['original_sha256'], audit.sha256(source))
            self.assertEqual(records[0]['redacted_lines'], 2)


if __name__ == '__main__':
    unittest.main()
