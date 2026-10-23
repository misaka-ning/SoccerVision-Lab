from pathlib import Path
import struct
import tempfile
import unittest

from audit_robot import sha256
from prepare_val_cases import png_hw, val_file
from stage0_robot import verify_sources


class Stage0Guards(unittest.TestCase):
    def test_source_drift_blocks_before_gpu_or_engine_use(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.py'
            source.write_text('original')
            expected = sha256(source)
            source.write_text('changed')
            with self.assertRaisesRegex(RuntimeError, 'source/config changed'):
                verify_sources(dict(sources=[dict(path=str(source), sha256=expected)]))

    def test_val_boundary_rejects_test_or_indirect_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            val = root / 'val'; test = root / 'test'
            val.mkdir(); test.mkdir()
            good = val / 'frame.png'; good.write_bytes(b'')
            bad = test / 'frame.png'; bad.write_bytes(b'')
            self.assertEqual(val_file(good, val), good)
            with self.assertRaises(ValueError):
                val_file(bad, val)
            (val / 'link.png').symlink_to(bad)
            with self.assertRaises(ValueError):
                val_file(val / 'link.png', val)

    def test_native_shape_reads_png_header_without_resizing(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'image.png'
            p.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + struct.pack('>II', 672, 376))
            self.assertEqual(png_hw(p), [376, 672])


if __name__ == '__main__':
    unittest.main()
