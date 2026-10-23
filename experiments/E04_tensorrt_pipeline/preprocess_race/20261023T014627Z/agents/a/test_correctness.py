"""CPU fake inference, real stereo/tracker/payload pipeline and cleanup checks."""

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import torch

from correctness import _Capture, _differences, _snapshot, run_correctness
from soccer_perception.adapters.yolo import YoloBallDetector
from soccer_perception.ros.node import config_from_ros_params


class Boxes:
    def __init__(self, rows):
        self.data = torch.tensor(rows, dtype=torch.float32).reshape(-1, 6)

    def __len__(self):
        return len(self.data)

    @property
    def xyxy(self):
        return self.data[:, :4]

    @property
    def conf(self):
        return self.data[:, 4]

    @property
    def cls(self):
        return self.data[:, 5]


class Predictor:
    def __init__(self, owner):
        self.owner = owner
        self.active_variant = None

    def preprocess(self, images):
        value = torch.empty((2, 3, 640, 640), dtype=torch.float32)
        for eye, image in enumerate(images):
            value[eye].fill_(float(image[0, 0, 0]) / 255.0)
        return value

    def inference(self, value):
        if self.owner.baseline_failure and self.active_variant is None:
            raise RuntimeError("mock R0 inference failure")
        for name in ("calls", "replay_count", "input_update_count", "output_clone_count"):
            self.owner.stats["engine"][name] += 1
        return [torch.full((2, 5, 8400), float(value[0, 0, 0, 0]), dtype=torch.float32)]


class Model:
    def __init__(self, owner):
        self.owner = owner
        self.predictor = Predictor(owner)

    def predict(self, images, **kwargs):
        self.owner.stats["postprocess"]["predict_calls"] += 1
        raw = self.predictor.inference(self.predictor.preprocess(images))
        # Emulate later postprocessing mutating the raw tensor. Capture must
        # already own a copy rather than expose this same tensor storage.
        self.owner.raw_before_mutation.append(float(raw[0][0, 0, 0]))
        raw[0].fill_(99)
        left = Boxes([[18, 8, 22, 12, .9, 0], [3, 2, 5, 4, .5, 0]])
        right = Boxes([[14, 8, 18, 12, .8, 0]])
        if self.owner.bad_final and self.predictor.active_variant == "canvas":
            left.data[1, 0] += 3  # final box later dropped by top_k=1
        return [SimpleNamespace(boxes=left, masks=None), SimpleNamespace(boxes=right, masks=None)]


class Detector(YoloBallDetector):
    def __init__(self):
        super().__init__(Path("frozen.engine"), .45, 640, "cpu", [0], False,
                         optimization="a2_graph")
        self.events = []
        self.baseline_failure = False
        self.bad_final = False
        self.raw_before_mutation = []

    def load(self):
        if self.model is not None:
            raise AssertionError("Loaded twice without cleanup")
        self.events.append("load")
        self.model = Model(self)
        self.names = {0: "football"}
        self.stats = {
            "engine": dict(effective="graph", capture_count=1, fallback_count=0, last_error=None,
                           calls=1, replay_count=1, input_update_count=1, output_clone_count=1),
            "postprocess": dict(effective="a2", fallback_count=0, last_error=None, predict_calls=1),
            "preprocess": dict(effective="c0", fallback_count=0, last_error=None),
        }

    def optimization_status(self):
        return dict(mode="a2_graph", enabled=self.model is not None,
                    state={"components": copy.deepcopy(self.stats)})

    def close(self):
        if self.model is not None:
            pred = self.model.predictor
            assert "preprocess" not in vars(pred), "capture/candidate still owns preprocess"
            assert "inference" not in vars(pred), "capture still owns inference"
            assert "_result_to_candidates" not in vars(self), "capture still owns converter"
            assert "load" not in vars(self), "temporary load no-op was not restored"
            self.events.append("close")
        self.model = None


class Candidate:
    def __init__(self, predictor, variant, behavior):
        self.predictor, self.variant = predictor, variant
        self.behavior = behavior
        self.original = predictor.preprocess
        self.calls = 0
        self.restored = False
        predictor.active_variant = variant

        def apply(images):
            self.calls += 1
            if behavior == "exception":
                raise ValueError("mock candidate exception")
            value = self.original(images)
            if behavior == "different":
                value[0, 0, 0, 0] += .1
            return value

        self.wrapper = apply
        predictor.preprocess = apply

    def describe(self):
        return dict(calls=self.calls, success_count=self.calls, fallback_count=0,
                    last_error=None, effective=self.variant, restored=self.restored)

    def restore(self):
        assert self.predictor.preprocess is self.wrapper, "outer capture not removed first"
        self.predictor.owner.events.append("restore_" + self.variant)
        self.predictor.__dict__.pop("preprocess")
        self.predictor.active_variant = None
        self.restored = True


class CorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        package = Path(__file__).resolve().parents[2] / "source/soccer_perception_ros"
        with patch("soccer_perception.resources.package_share_directory", return_value=package), \
                patch("soccer_perception.ros.node.resolve_resource_path", side_effect=Path):
            self.config = replace(config_from_ros_params(), zed_viser_enabled=False,
                                  disable_cudnn=False, yolo_top_k=1)
        self.doc = {"split": "val", "test_accessed": False, "pairs": [
            {"pair_key": "one", "left": "one_l", "right": "one_r"},
            {"pair_key": "two", "left": "two_l", "right": "two_r"}]}
        self.images = {name: np.full((24, 32, 3), i * 20 + 10, np.uint8)
                       for i, name in enumerate(("one_l", "one_r", "two_l", "two_r"))}
        self.calib = dict(K=[[100, 0, 16], [0, 100, 12], [0, 0, 1]], baseline_m=.063,
                          image_size=[32, 24], fps=30)

    def invoke(self, detector, directory, behavior=None):
        def install(pred, variant):
            return Candidate(pred, variant, (behavior or {}).get(variant, "same"))
        return run_correctness(detector, self.config, self.doc, self.images, self.calib,
                               install, directory)

    def test_real_pipeline_exact_and_safe_restore_every_variant(self):
        detector = Detector()
        originals = {k: v.copy() for k, v in self.images.items()}
        with tempfile.TemporaryDirectory() as directory:
            report = self.invoke(detector, directory)
            self.assertTrue(report["passed"], report)
            self.assertTrue(report["canvas"]["passed"])
            self.assertTrue(report["reuse"]["passed"])
            rows = json.loads((Path(directory) / "per_pair.json").read_text())
            self.assertEqual(len(rows), 6)
            self.assertEqual(rows[0]["frame_idx"], 0)
            self.assertEqual(rows[0]["replay_timestamp"], 1000)
            self.assertNotEqual(rows[0]["input"]["sha256"], rows[1]["input"]["sha256"])
            self.assertEqual(rows[0]["candidate_counts"], [1, 1])
            self.assertEqual(rows[0]["final_boxes"][0]["shape"], [2, 6])
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()),
                             ["correctness.json", "per_pair.json"])
        self.assertEqual(detector.events,
                         ["load", "close", "load", "restore_canvas", "close",
                          "load", "restore_reuse", "close"])
        self.assertIsNone(detector.model)
        for name in self.images:
            np.testing.assert_array_equal(self.images[name], originals[name])

    def test_changed_candidate_fails_without_hiding_or_excluding_other_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self.invoke(Detector(), directory, {"canvas": "different"})
            self.assertFalse(report["passed"])
            self.assertFalse(report["canvas"]["passed"])
            self.assertTrue(report["reuse"]["passed"])
            self.assertEqual(report["eligible_candidates"], ["reuse"])
            errors = str(report["canvas"]["errors"])
            self.assertIn("input/0: array bytes differ", errors)
            self.assertIn("raw/0", errors)

    def test_all_final_boxes_checked_before_topk(self):
        detector = Detector()
        detector.bad_final = True
        with tempfile.TemporaryDirectory() as directory:
            report = self.invoke(detector, directory)
            self.assertFalse(report["canvas"]["passed"])
            errors = str(report["canvas"]["errors"])
            self.assertIn("final_boxes/0: array bytes differ", errors)
            self.assertNotIn("candidates/", errors)
            self.assertTrue(report["reuse"]["passed"])

    def test_candidate_exception_keeps_traceback_and_restores_before_close(self):
        detector = Detector()
        with tempfile.TemporaryDirectory() as directory:
            report = self.invoke(detector, directory, {"canvas": "exception"})
            self.assertFalse(report["canvas"]["passed"])
            self.assertIn("mock candidate exception", str(report["canvas"]["errors"]))
            self.assertIn("traceback", report["canvas"]["errors"][0])
            self.assertTrue(report["canvas"]["restore_passed"])
            self.assertTrue(report["reuse"]["passed"])
        self.assertIsNone(detector.model)

    def test_r0_failure_writes_report_then_raises(self):
        detector = Detector()
        detector.baseline_failure = True
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "R0 correctness reference failed"):
                self.invoke(detector, directory)
            report = json.loads((Path(directory) / "correctness.json").read_text())
            self.assertFalse(report["R0"]["passed"])
            self.assertFalse(report["canvas"]["passed"])
            self.assertFalse(report["reuse"]["passed"])
            self.assertIn("mock R0 inference failure", str(report))
        self.assertEqual(detector.events, ["load", "close"])

    def test_snapshot_owns_raw_storage_and_checks_dtype_shape_bytes(self):
        raw = torch.ones((2, 5, 8400))
        saved = _snapshot([raw])
        raw.fill_(99)
        self.assertTrue(np.all(saved["items"][0]["data"] == 1))
        self.assertTrue(_differences(np.array([1], np.float32), np.array([1], np.float64)))
        self.assertTrue(_differences(np.array([1], np.float32), np.array([[1]], np.float32)))
        self.assertFalse(_differences(saved, _snapshot([torch.ones((2, 5, 8400))])))


if __name__ == "__main__":
    unittest.main()
