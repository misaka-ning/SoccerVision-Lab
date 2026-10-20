"""Exercise training orchestration without loading weights or importing torch."""

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location("football_train", Path(__file__).resolve().parents[1] / "train.py")
train = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(train)


class TrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "weights.pt").touch()
        (self.root / "data.yaml").write_text("train: images/train\nval: images/val\nnames: {0: football}\n")
        self.config = self.root / "train.yaml"
        self.config.write_text("model: weights.pt\ndata: data.yaml\nproject: output\nepochs: 10\nbatch: 8\n")
        self.root_patch = patch.object(train, "PROJECT_ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def args(self, *extra):
        return train.parse_args(["--config", str(self.config), *extra])

    def test_paths_and_cli_overrides_ignore_working_directory(self):
        (self.root / "alternative.yaml").write_text("train: images/train\nval: images/val\nnames: {0: football}\n")
        previous = Path.cwd()
        try:
            os.chdir("/tmp")
            model, options = train.build_plan(self.args("--data", "alternative.yaml", "--epochs", "2", "--device", "cpu"))
        finally:
            os.chdir(previous)
        self.assertEqual(model, str(self.root / "weights.pt"))
        self.assertEqual(options["data"], str(self.root / "alternative.yaml"))
        self.assertEqual(options["project"], str(self.root / "output"))
        self.assertEqual(options["epochs"], 2)
        self.assertEqual(options["device"], "cpu")

    def test_dry_run_does_not_import_or_load_model(self):
        fake = types.ModuleType("ultralytics")
        fake.YOLO = Mock(side_effect=AssertionError("must not load model"))
        with patch.dict(sys.modules, {"ultralytics": fake}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(train.main(["--config", str(self.config), "--dry-run"]), 0)
        fake.YOLO.assert_not_called()

    def test_training_receives_resolved_arguments(self):
        fake = types.ModuleType("ultralytics")
        fake.YOLO = Mock()
        with patch.dict(sys.modules, {"ultralytics": fake}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(train.main(["--config", str(self.config), "--device", "cpu"]), 0)
        fake.YOLO.assert_called_once_with(str(self.root / "weights.pt"), task="detect")
        options = fake.YOLO.return_value.train.call_args.kwargs
        self.assertEqual(options["data"], str(self.root / "data.yaml"))
        self.assertEqual(options["epochs"], 10)
        self.assertNotIn("model", options)

    def test_resume_preserves_checkpoint_options(self):
        model, options = train.build_plan(train.parse_args(["--resume", "weights.pt", "--device", "cpu"]))
        self.assertEqual(model, str(self.root / "weights.pt"))
        self.assertEqual(options, {"resume": True, "device": "cpu"})
        for option, value in (("--epochs", "20"), ("--data", "data.yaml")):
            with self.subTest(option=option), self.assertRaisesRegex(ValueError, "checkpoint"):
                train.build_plan(train.parse_args(["--resume", "weights.pt", option, value]))

    def test_missing_files_and_invalid_parameters(self):
        with self.assertRaisesRegex(ValueError, "正整数"):
            train.build_plan(self.args("--epochs", "0"))
        with self.assertRaisesRegex(ValueError, "batch"):
            train.build_plan(self.args("--batch", "0"))
        (self.root / "weights.pt").unlink()
        with self.assertRaisesRegex(ValueError, "不存在"):
            train.build_plan(self.args())

    def test_malformed_yaml_reports_error(self):
        self.config.write_text("model: [broken\n")
        with contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(train.main(["--config", str(self.config)]), 2)
        self.assertIn("YAML 格式错误", error.getvalue())


if __name__ == "__main__":
    unittest.main()
