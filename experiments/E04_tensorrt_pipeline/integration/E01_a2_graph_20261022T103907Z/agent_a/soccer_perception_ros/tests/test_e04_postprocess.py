"""CPU equivalence checks, plus opt-in frozen-Val replay via E04_GOLDEN_DIR."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np
import torch

from soccer_perception.adapters.yolo import YoloBallDetector
from soccer_perception.optimizations.postprocess import install


class Boxes:
    """Use real CPU torch tensors with the audited Boxes access semantics."""
    def __init__(self, values):
        self.data = torch.as_tensor(values, dtype=torch.float32).reshape(-1, 6)

    def __len__(self):
        return len(self.data)

    @property
    def xyxy(self):
        return self.data[:, :4]

    @property
    def conf(self):
        return self.data[:, -2]

    @property
    def cls(self):
        return self.data[:, -1]


def result(values=()):
    return SimpleNamespace(boxes=Boxes(values), masks=None)


class Model:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def predict(self, *args, **kwargs):
        self.calls.append((args, kwargs.copy()))
        return self.results


def detector(results):
    det = YoloBallDetector.__new__(YoloBallDetector)
    det.model = Model(results)
    det.names = {0: "football", 3: "other"}
    det.conf, det.imgsz, det.device, det.half = 0.45, 640, "0", True
    det.class_ids = [0]
    det.runtime_model_path = Path("frozen.engine")
    det.name = "frozen-results-cpu"
    det.optimization = "none"
    det._optimization_handle = None
    det._last_optimization_status = None
    det.load = lambda: None
    return det


def serialized(groups):
    return [[x.to_dict() for x in group] for group in groups]


FRAMES = [np.zeros((4, 4, 3), np.uint8), np.zeros((4, 4, 3), np.uint8)]


class PostprocessTests(unittest.TestCase):
    def compare_variants(self, results, top_k):
        det = detector(results)
        baseline = serialized(det.detect_candidates_batch(FRAMES, top_k=top_k))
        original_predict = det.model.predict.__func__
        original_convert = det._result_to_candidates.__func__
        for variant in ("a0", "a1", "a2", "a1+a2"):
            with self.subTest(variant=variant, top_k=top_k):
                handle = install(det, variant)
                actual = serialized(det.detect_candidates_batch(FRAMES, top_k=top_k))
                self.assertEqual(actual, baseline)
                self.assertEqual(handle.describe()["fallback_count"], 0)
                handle.restore()
                handle.restore()
                self.assertEqual(handle.describe()["effective"], "a0")
                self.assertIs(det.model.predict.__func__, original_predict)
                self.assertIs(det._result_to_candidates.__func__, original_convert)
        return baseline

    def test_empty_left_right_and_asymmetry(self):
        for results in ([result(), result()], [result([[1, 2, 4, 6, .9, 0]]), result()],
                        [SimpleNamespace(boxes=None, masks=None), result([[2, 4, 8, 9, .7, 0]])]):
            self.compare_variants(results, 5)

    def test_dense_overlapping_ties_negative_bounds_tiny_boxes_and_topk(self):
        # Final NMS results may contain overlapping survivors; this module must
        # neither remove nor reorder equal-score survivors at any top_k value.
        left = result([
            [1.5, 2.5, 1.5, 2.2, .9, 0], [-2.5, -1.5, 10.2, 20.7, .8, 3],
            [0, 0, 20, 20, .9, 0], [1, 1, 21, 21, .7, 0],
            [2, 2, 22, 22, .7, 0], [3, 3, 23, 23, .7, 0],
            [4, 4, 24, 24, .7, 0], [639, 479, 642, 481, .95, 0],
        ])
        right = result([[31, 2, 34, 5, .9, 0]])
        for top_k in (None, -1, 0, 1, 5, 20):
            actual = self.compare_variants([left, right], top_k)
            self.assertEqual(len(actual[0]), min(top_k, 8) if top_k and top_k > 0 else 8)
        self.assertEqual(self.compare_variants([left, right], None)[0][1]["bbox"], [2, 2, 1, 1])

    def test_predict_arguments_and_original_objects_are_preserved(self):
        results = [result([[1, 2, 4, 8, .9, 0]]), result([[10, 20, 40, 80, .8, 0]])]
        original_data = [r.boxes.data for r in results]
        results[0].boxes.xywh = "obsolete cached property"
        det = detector(results)
        h = install(det, "a2")
        copied = det.model.predict(FRAMES, conf=.45, classes=[0], custom="same")
        self.assertEqual(det.model.calls[-1][1], {"conf": .45, "classes": [0], "custom": "same"})
        self.assertIsNot(copied[0], results[0])
        self.assertIsNot(copied[0].boxes, results[0].boxes)
        self.assertNotIn("xywh", vars(copied[0].boxes))
        self.assertIn("xywh", vars(results[0].boxes))
        for original, tensor in zip(results, original_data):
            self.assertIs(original.boxes.data, tensor)
        self.assertEqual(h.describe()["packed_batches"], 1)
        self.assertEqual(h.describe()["packed_rows"], 2)
        self.assertEqual(h.describe()["d2h_calls"], 0)  # this test uses CPU tensors
        h.restore()
        self.assertEqual(serialized(det.detect_candidates_batch(FRAMES))[0][0]["bbox"], [1, 2, 3, 6])

    def test_changed_inputs_are_not_cached_or_replayed(self):
        det = detector([result([[1, 2, 4, 8, .9, 0]]), result()])
        h = install(det, "a2")
        first = serialized(det.detect_candidates_batch(FRAMES))
        det.model.results = [result(), result([[91, 92, 95, 98, .7, 0]])]
        second = serialized(det.detect_candidates_batch(FRAMES))
        self.assertNotEqual(first, second)
        self.assertEqual(second[0], [])
        self.assertEqual(second[1][0]["bbox"], [91, 92, 4, 6])
        self.assertEqual(h.describe()["predict_calls"], 2)
        h.restore()

    def test_unsupported_a2_results_fall_back_without_repeating_inference(self):
        for mutation in ("dtype", "track", "masks", "generator"):
            values = [result([[0, 0, 4, 4, .8, 0]]), result()]
            if mutation == "dtype":
                values[0].boxes.data = values[0].boxes.data.double()
            if mutation == "track":
                values[0].boxes.data = torch.tensor([[0, 0, 4, 4, 7, .8, 0]])
            if mutation == "masks":
                values[0].masks = SimpleNamespace(xy=[])
            original = iter(values) if mutation == "generator" else values
            det = detector(original)
            h = install(det, "a2")
            self.assertIs(det.model.predict(FRAMES), original)
            self.assertEqual(len(det.model.calls), 1)
            self.assertEqual(h.describe()["fallback_count"], 1)
            self.assertIsNotNone(h.describe()["last_error"])
            h.restore()

    def test_a1_masks_use_original_centroid_and_radius(self):
        left = result([[0, 0, 12, 12, .8, 0]])
        left.masks = SimpleNamespace(xy=[np.array([[2, 2], [8, 2], [2, 8]], np.float32)])
        det = detector([left, result()])
        expected = serialized(det.detect_candidates_batch(FRAMES))
        h = install(det, "a1")
        self.assertEqual(serialized(det.detect_candidates_batch(FRAMES)), expected)
        self.assertEqual(h.describe()["fallback_count"], 1)
        h.restore()

    def test_a2_preserves_legacy_fast_results_without_claiming_a_transfer(self):
        # A2 is deployed only with the ordinary predictor. If a caller directly
        # supplies E02 CPU results, retain their existing candidate semantics;
        # zero packed batches must not be mistaken for an exercised A2 copy.
        from soccer_perception.adapters.fast_postprocess import FastDetectionResult
        values = [FastDetectionResult(np.asarray([[1, 2, 4, 8, .9, 0]], np.float32)),
                  FastDetectionResult(np.empty((0, 6), np.float32))]
        det = detector(values)
        expected = serialized(det.detect_candidates_batch(FRAMES, top_k=5))
        h = install(det, "a2")
        self.assertIs(det.model.predict(FRAMES), values)
        self.assertEqual(serialized(det.detect_candidates_batch(FRAMES, top_k=5)), expected)
        self.assertEqual(h.describe()["packed_batches"], 0)
        self.assertEqual(h.describe()["fallback_count"], 0)
        h.restore()

    def test_a2_returned_storage_survives_later_calls_and_source_mutation(self):
        values = [result([[1, 2, 4, 8, .9, 0]]), result([[10, 20, 40, 80, .8, 0]])]
        det = detector(values)
        h = install(det, "a2")
        first = det.model.predict(FRAMES)
        saved = [item.boxes.data.clone() for item in first]
        values[0].boxes.data.fill_(-11)
        det.model.results = [result([[91, 92, 95, 98, .7, 0]]), result()]
        second = det.model.predict(FRAMES)
        for item, expected in zip(first, saved):
            torch.testing.assert_close(item.boxes.data, expected, rtol=0, atol=0)
        self.assertEqual(second[0].boxes.data[0, 0], 91)
        self.assertEqual(first[0].boxes.data[0, 0], 1)
        h.restore()

    def test_a2_restore_ownership_conflict_is_retryable(self):
        det = detector([result(), result()])
        original = det.model.predict.__func__
        h = install(det, "a2")
        installed = det.model.predict
        replacement = lambda *args, **kwargs: []
        det.model.predict = replacement
        with self.assertRaises(RuntimeError):
            h.restore()
        self.assertIs(det.model.predict, replacement)
        self.assertIs(det._e04_postprocess_handle, h)
        self.assertFalse(h.describe()["restored"])
        det.model.predict = installed
        h.restore()
        self.assertIs(det.model.predict.__func__, original)
        self.assertNotIn("_e04_postprocess_handle", vars(det))

    def test_install_rollback_off_by_default_and_a3_unavailable(self):
        det = detector([result(), result()])
        self.assertNotIn("predict", vars(det.model))
        h = install(det)
        self.assertEqual(h.describe()["effective"], "a0")
        self.assertNotIn("predict", vars(det.model))
        with self.assertRaises(RuntimeError):
            install(det, "a1")
        h.restore()
        h = install(det, "a3")
        self.assertEqual(h.describe()["effective"], "a0")
        self.assertFalse(h.describe()["available"])
        self.assertEqual(h.describe()["fallback_count"], 1)
        self.assertNotIn("predict", vars(det.model))
        h.restore()
        with self.assertRaises(ValueError):
            install(det, "not-a-variant")
        det.model = None
        with self.assertRaises(RuntimeError):
            install(det, "a1+a2")
        self.assertNotIn("_result_to_candidates", vars(det))

    def test_restore_preserves_preexisting_instance_override(self):
        det = detector([result(), result()])
        original = det._result_to_candidates
        det._result_to_candidates = lambda *args, **kwargs: original(*args, **kwargs)
        converter = det._result_to_candidates
        predictor = lambda *args, **kwargs: det.model.results
        det.model.predict = predictor
        h = install(det, "a1+a2")
        h.restore()
        self.assertIs(det._result_to_candidates, converter)
        self.assertIs(det.model.predict, predictor)


@unittest.skipUnless(os.environ.get("E04_GOLDEN_DIR"), "set E04_GOLDEN_DIR to frozen Val Golden")
class GoldenTests(unittest.TestCase):
    def test_all_final_boxes_match_candidates_including_left_right(self):
        root = Path(os.environ["E04_GOLDEN_DIR"])
        golden = json.loads((root / "golden.json").read_text())
        self.assertEqual(golden["split"], "val")
        self.assertIs(golden["test_accessed"], False)
        cases = PostprocessTests()
        for item in golden["records"]:
            with self.subTest(pair=item["pair_key"]):
                with np.load(root / (item["pair_key"] + ".npz")) as arrays:
                    values = [result(arrays[key]) for key in ("left_final_boxes", "right_final_boxes")]
                    actual = cases.compare_variants(values, 5)
                    self.assertEqual(actual, item["candidates"])

    def test_real_downstream_stereo_tracking_and_ros_protocol_match_golden(self):
        from dataclasses import replace
        from soccer_perception.types import BackendConfig, CameraIntrinsics, StereoFrame
        from soccer_perception.pipeline import SoccerPerceptionPipeline
        from soccer_perception.core.tracking import AlphaBetaBallTracker
        from soccer_perception.ros.output import build_ball_position_camera_payload

        root = Path(os.environ["E04_GOLDEN_DIR"])
        golden = json.loads((root / "golden.json").read_text())
        saved_config = json.loads((root / "effective_runtime.json").read_text())["original_config"]
        # Frozen Golden predates the optional production switch. Keep its
        # original behavior without rewriting the archived reference config.
        if "yolo_optimization" in BackendConfig.__dataclass_fields__:
            saved_config.setdefault("yolo_optimization", "none")
        config = replace(BackendConfig(**saved_config), zed_viser_enabled=False)
        calibration = json.loads((root / "calibration.json").read_text())
        intrinsics = CameraIntrinsics(np.asarray(calibration["K"], np.float64),
                                     calibration["baseline_m"], calibration["fps"], tuple(calibration["image_size"]))
        image = np.zeros((intrinsics.image_size[1], intrinsics.image_size[0], 3), np.uint8)
        originals = []
        for item in golden["records"]:
            with np.load(root / (item["pair_key"] + ".npz")) as arrays:
                originals.append([result(arrays[key]) for key in ("left_final_boxes", "right_final_boxes")])

        class Source:
            index = 0
            def open(self): return intrinsics
            def close(self): pass
            def read(self):
                if self.index == len(originals): return None
                item = golden["records"][self.index]
                self.index += 1
                return StereoFrame(item["replay_timestamp"], image, image, item["frame_idx"])

        class NullVisualizer:
            def open(self): pass
            def close(self): pass
            def update(self, *values): pass

        def equivalent(expected, actual):
            if isinstance(expected, dict):
                self.assertEqual(expected.keys(), actual.keys())
                for key in expected: equivalent(expected[key], actual[key])
            elif isinstance(expected, list):
                self.assertEqual(len(expected), len(actual))
                for a, b in zip(expected, actual): equivalent(a, b)
            elif isinstance(expected, float):
                self.assertAlmostEqual(expected, actual, delta=1e-12)
            else:
                self.assertEqual(expected, actual)

        for variant in ("a0", "a1", "a2", "a1+a2"):
            det = detector(originals[0])
            tracker = AlphaBetaBallTracker(max_coast_frames=config.max_coast_frames,
                                          max_coast_time_s=config.max_coast_time_s,
                                          velocity_decay=config.velocity_decay)
            pipeline = SoccerPerceptionPipeline(Source(), det, tracker, config, visualizer=NullVisualizer())
            h = install(det, variant)
            pipeline.open()
            try:
                for item, values in zip(golden["records"], originals):
                    det.model.results = values
                    packet = pipeline.next_packet()
                    equivalent(item["selected"], [x.to_dict() if x else None for x in (packet.left_det, packet.right_det)])
                    equivalent(item["measurement"], packet.ball_3d_measurement.to_dict())
                    equivalent(item["track"], packet.camera_track_state.to_dict())
                    equivalent(item["ros_payload"], build_ball_position_camera_payload(packet))
            finally:
                pipeline.close()
                h.restore()


if __name__ == "__main__":
    unittest.main()
