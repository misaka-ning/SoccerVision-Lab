"""Artifact lifecycle regressions without CUDA, TensorRT or Ultralytics."""
import fcntl
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from soccer_perception.adapters.yolo import YoloBallDetector
from soccer_perception.model_artifacts import build_engine, require_engine


class ModelArtifactTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.model = self.root / 'ball.pt'
        self.model.write_bytes(b'weights')
        self.engine = self.model.with_suffix('.engine')
        self.detector = YoloBallDetector(self.model, .45, 640, 'cuda:0', [0], False,
                                         tensorrt=True, trt_batch=2)
        self.exports = []
        def factory(path):
            def export(**kwargs):
                self.exports.append(kwargs)
                Path(path).with_suffix('.onnx').write_bytes(b'onnx')
                engine = Path(path).with_suffix('.engine')
                engine.write_bytes(b'engine')
                return str(engine)
            return Mock(export=export)
        self.yolo = Mock(side_effect=factory)

    def test_startup_does_not_export_and_explicit_build_reuses_matching_engine(self):
        with self.assertRaisesRegex(FileNotFoundError, 'build_engine.sh'):
            self.detector._prepare_model_path()
        self.assertEqual(list(self.root.iterdir()), [self.model])
        self.assertEqual(build_engine(self.detector, self.yolo), self.engine)
        self.assertEqual(require_engine(self.detector), self.engine)
        self.assertEqual(build_engine(self.detector, self.yolo), self.engine)
        self.assertEqual(len(self.exports), 1)
        self.assertEqual(self.model.with_suffix('.onnx').read_bytes(), b'onnx')
        self.assertFalse(list(self.root.glob('.export-*')))

    def test_weights_settings_and_engine_changes_require_explicit_rebuild(self):
        build_engine(self.detector, self.yolo)
        for attribute, value in [('imgsz', 320), ('trt_batch', 1), ('half', True), ('trt_dynamic', True)]:
            previous = getattr(self.detector, attribute)
            setattr(self.detector, attribute, value)
            with self.assertRaisesRegex(RuntimeError, '--force'):
                require_engine(self.detector)
            setattr(self.detector, attribute, previous)
        self.model.write_bytes(b'new weights')
        with self.assertRaisesRegex(RuntimeError, '--force'):
            build_engine(self.detector, self.yolo)
        build_engine(self.detector, self.yolo, force=True)
        self.engine.write_bytes(b'damaged')
        with self.assertRaisesRegex(RuntimeError, '--force'):
            require_engine(self.detector)

    def test_legacy_engine_requires_explicit_adoption_and_is_preserved(self):
        self.engine.write_bytes(b'legacy engine')
        with self.assertRaisesRegex(RuntimeError, '--adopt-existing'):
            build_engine(self.detector, self.yolo)
        build_engine(self.detector, self.yolo, adopt_existing=True)
        self.assertEqual(require_engine(self.detector), self.engine)
        self.assertEqual(self.engine.read_bytes(), b'legacy engine')
        self.yolo.assert_not_called()

    def test_failed_export_preserves_existing_engine_and_onnx(self):
        build_engine(self.detector, self.yolo)
        self.yolo.side_effect = RuntimeError('export failed')
        with self.assertRaisesRegex(RuntimeError, 'export failed'):
            build_engine(self.detector, self.yolo, force=True)
        self.assertEqual(self.engine.read_bytes(), b'engine')
        self.assertEqual(self.model.with_suffix('.onnx').read_bytes(), b'onnx')
        self.assertEqual(require_engine(self.detector), self.engine)

    def test_existing_onnx_conflict_requires_force(self):
        self.model.with_suffix('.onnx').write_bytes(b'old onnx')
        with self.assertRaisesRegex(RuntimeError, 'Existing ONNX differs'):
            build_engine(self.detector, self.yolo)
        self.assertFalse(self.engine.exists())
        self.assertEqual(self.model.with_suffix('.onnx').read_bytes(), b'old onnx')
        build_engine(self.detector, self.yolo, force=True)
        self.assertEqual(self.model.with_suffix('.onnx').read_bytes(), b'onnx')

    def test_concurrent_exports_fail_before_loading_model(self):
        with (self.root / '.engine-build.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, 'Another model export'):
                build_engine(self.detector, self.yolo)
        self.yolo.assert_not_called()

    def test_explicit_engine_can_run_without_pt_but_must_exist(self):
        self.detector.model_path = self.engine
        with self.assertRaises(FileNotFoundError):
            require_engine(self.detector)
        self.engine.write_bytes(b'provided engine')
        self.assertEqual(require_engine(self.detector), self.engine)
        with self.assertRaisesRegex(ValueError, 'source .pt'):
            build_engine(self.detector, self.yolo, force=True)

    def test_engine_destination_cannot_overwrite_source_weights(self):
        self.detector.engine_path = self.model
        with self.assertRaisesRegex(ValueError, 'must end in .engine'):
            build_engine(self.detector, self.yolo, force=True)
        self.assertEqual(self.model.read_bytes(), b'weights')

    def test_custom_engine_destination_and_pointer_rejection(self):
        self.detector.engine_path = self.root / 'external/custom.engine'
        self.assertEqual(build_engine(self.detector, self.yolo), self.detector.engine_path)
        self.assertTrue(self.model.with_suffix('.onnx').exists())
        self.model.write_bytes(b'version https://git-lfs.github.com/spec/v1\n')
        with self.assertRaisesRegex(ValueError, 'Git LFS pointer'):
            build_engine(self.detector, self.yolo, force=True)


class ModelMigrationTests(unittest.TestCase):
    def test_migration_is_repeatable_and_conflicts_preserve_both_versions(self):
        script = Path(__file__).resolve().parents[2] / 'deployment/migrate_models.py'
        if not script.exists():
            self.skipTest('Deployment migration helper is only present in a full checkout')
        spec = importlib.util.spec_from_file_location('migrate_models', script)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new = root / 'install/models', root / 'source/models'
            old.mkdir(parents=True)
            (old / 'ball.engine').write_bytes(b'old engine')
            (old / 'ball.onnx').write_bytes(b'old onnx')
            self.assertEqual(len(module.migrate(old, new)), 2)
            self.assertEqual(module.migrate(old, new), [])
            (new / 'ball.engine').write_bytes(b'new engine')
            (old / 'another.engine').write_bytes(b'another')
            with self.assertRaisesRegex(RuntimeError, 'migration conflict'):
                module.migrate(old, new)
            self.assertFalse((new / 'another.engine').exists())
            self.assertEqual((old / 'ball.engine').read_bytes(), b'old engine')
            self.assertEqual((new / 'ball.engine').read_bytes(), b'new engine')
