"""Golden comparison against frozen robot Ultralytics and existing Torch NMS."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import torch
import torchvision

from soccer_perception.adapters.fast_postprocess import (
    batch_rows_to_numpy, make_fast_predictor_class, rows_to_candidates, single_class_nms,
)
from soccer_perception.adapters.yolo import YoloBallDetector


def reference_module():
    path = Path(__file__).with_name("fixtures") / "golden_postprocess_8_3_159.py"
    spec = importlib.util.spec_from_file_location("golden_postprocess", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GOLDEN = reference_module()


def fast(raw, **kwargs):
    return single_class_nms(
        raw, nms=GOLDEN.nms_fallback, xywh2xyxy=GOLDEN.xywh2xyxy,
        conf_thres=kwargs.pop("conf_thres", 0.0008),
        iou_thres=kwargs.pop("iou_thres", 0.7), **kwargs,
    )


def reference(raw, **kwargs):
    with patch.object(torchvision.ops, "nms", GOLDEN.nms_fallback):
        return GOLDEN.non_max_suppression(
            raw.clone(), conf_thres=kwargs.pop("conf_thres", 0.0008),
            iou_thres=kwargs.pop("iou_thres", 0.7), **kwargs,
        )


class SingleClassGoldenTest(unittest.TestCase):
    def assert_matches(self, raw, **kwargs):
        before = raw.clone()
        actual, expected = fast(raw, **kwargs), reference(raw, **kwargs)
        self.assertEqual(len(actual), len(expected))
        for row, golden in zip(actual, expected):
            torch.testing.assert_close(row, golden, rtol=0, atol=0)
        torch.testing.assert_close(raw, before, rtol=0, atol=0)
        return actual

    def test_empty_and_strict_low_confidence(self):
        raw = torch.zeros((2, 5, 9))
        raw[:, :4] = torch.tensor([10, 20, 4, 6])[None, :, None]
        raw[0, 4, :4] = torch.tensor([0, 0.000799, 0.0008, 0.000801])
        actual = self.assert_matches(raw)
        self.assertEqual(actual[0].shape[0], 1)
        self.assertEqual(actual[1].shape[0], 0)
        self.assert_matches(torch.zeros((2, 5, 0)))

    def test_overlap_boundary_degenerate_ties(self):
        rows = torch.tensor([
            [10, 10, 8, 8, 0.9], [10, 10, 8, 8, 0.9],
            [-5, -4, 20, 16, 0.8], [640, 640, 20, 20, 0.7],
            [30, 30, 0, 0, 0.6], [40, 40, -3, 8, 0.5],
            [50, 50, 8, -3, 0.4], [5, 5, 1, 1, 0.3],
        ], dtype=torch.float32)
        raw = torch.stack([rows.T, rows.flip(0).T])
        self.assert_matches(raw, iou_thres=0.0)
        self.assert_matches(raw, iou_thres=1.0)
        self.assert_matches(raw, classes=[0])
        self.assert_matches(raw, classes=[0, 1])
        self.assert_matches(raw, classes=[])
        self.assert_matches(raw, classes=[1])

    def test_random_order_max_nms_and_max_det(self):
        generator = torch.Generator().manual_seed(20261020)
        for count in (7, 100, 700):
            raw = torch.rand((2, 5, count), generator=generator)
            raw[:, :2] *= 640
            raw[:, 2:4] *= 100
            self.assert_matches(raw, max_det=5, max_nms=60)
            self.assert_matches(raw, max_det=0)

    def test_scale_and_batch_order(self):
        raw = torch.zeros((2, 5, 7))
        raw[0, :, 0] = torch.tensor([100, 200, 40, 40, 0.7])
        raw[1, :, 0] = torch.tensor([400, 200, 40, 40, 0.8])
        rows = self.assert_matches(raw)
        for row, shape in zip(rows, [(376, 672, 3), (480, 640, 3)]):
            GOLDEN.scale_boxes((640, 640), row[:, :4], shape)
        merged = batch_rows_to_numpy(rows)
        for actual, original in zip(merged, rows):
            np.testing.assert_array_equal(actual, original.numpy())
        old = merged[0].copy()
        batch_rows_to_numpy([rows[1], rows[0]])
        np.testing.assert_array_equal(merged[0], old)

    def test_rejects_unsupported_output(self):
        for raw in (torch.zeros((2, 84, 7)), torch.zeros((2, 5, 6)),
                    torch.zeros((2, 5, 7), dtype=torch.float16)):
            with self.assertRaises(ValueError):
                fast(raw)

    def test_predictor_factory_leaves_nms_untouched(self):
        before = torchvision.ops.nms
        self.assertTrue(issubclass(make_fast_predictor_class(), object))
        self.assertIs(before, torchvision.ops.nms)

    def test_predictor_fast_output_and_feature_fallback(self):
        from types import SimpleNamespace
        from ultralytics.models.yolo.detect.predict import DetectionPredictor
        from soccer_perception.adapters.fast_postprocess import FastDetectionResult
        cls = make_fast_predictor_class(nms=GOLDEN.nms_fallback)
        predictor = cls.__new__(cls)
        predictor.args = SimpleNamespace(task="detect", conf=0.0008, iou=0.7,
            classes=[0], max_det=300, verbose=False, save=False)
        predictor.model = SimpleNamespace(names={0: "football"}, end2end=False)
        raw = torch.zeros((2, 5, 7))
        raw[0, :, 0] = torch.tensor([100, 200, 40, 40, 0.7])
        raw[1, :, 0] = torch.tensor([400, 200, 40, 40, 0.8])
        image = torch.zeros((2, 3, 640, 640))
        originals = [np.zeros((376, 672, 3), np.uint8)] * 2
        actual = predictor.postprocess(raw, image, originals)
        self.assertTrue(all(isinstance(result, FastDetectionResult) for result in actual))
        expected = reference(raw)
        for result, row in zip(actual, expected):
            GOLDEN.scale_boxes((640, 640), row[:, :4], originals[0].shape)
            np.testing.assert_array_equal(result.rows, row.numpy())
        predictor.args.save = True
        with patch.object(DetectionPredictor, "postprocess", return_value="fallback") as legacy:
            self.assertEqual(predictor.postprocess(raw, image, originals), "fallback")
            legacy.assert_called_once()

    def test_batch_transfer_calls_cpu_once_and_empty_never(self):
        original = torch.Tensor.cpu
        calls = []
        def record_cpu(tensor, *args, **kwargs):
            calls.append(tensor.shape)
            return original(tensor, *args, **kwargs)
        with patch.object(torch.Tensor, "cpu", record_cpu):
            batch_rows_to_numpy([torch.zeros((3, 6)), torch.zeros((4, 6))])
            self.assertEqual(calls, [torch.Size([7, 6])])
            batch_rows_to_numpy([torch.zeros((0, 6)), torch.zeros((0, 6))])
            self.assertEqual(len(calls), 1)


class CandidateProtocolTest(unittest.TestCase):
    def test_matches_original_results_converter_for_top_k_and_ties(self):
        from types import SimpleNamespace
        rows = torch.tensor([
            [1.5, 2.5, 6.5, 8.5, 0.7, 0],
            [-3, -4, -3, -4, 0.9, 0],
            [2.5, 3.5, 10.5, 11.5, 0.7, 0],
            [5, 4, 2, 3, 0.1, 0],
        ])
        detector = YoloBallDetector(Path("frozen.engine"), 0.0008, 640, None, [0], True)
        detector.names = {0: "football"}
        result = SimpleNamespace(boxes=SimpleNamespace(
            xyxy=rows[:, :4], conf=rows[:, 4], cls=rows[:, 5],
        ), masks=None)
        # The original converter asks len(boxes), so model only that protocol.
        class Boxes:
            xyxy, conf, cls = rows[:, :4], rows[:, 4], rows[:, 5]
            def __len__(self):
                return len(rows)
        result.boxes = Boxes()
        for top_k in (None, -1, 0, 1, 2, 10):
            expected = detector._result_to_candidates(result, top_k=top_k)
            actual = rows_to_candidates(rows.numpy(), names=detector.names, top_k=top_k)
            self.assertEqual(len(actual), len(expected))
            for left, right in zip(actual, expected):
                np.testing.assert_array_equal(left.center, right.center)
                for key in ("bbox", "radius_px", "score", "class_id", "class_name", "source"):
                    self.assertEqual(getattr(left, key), getattr(right, key))

    def test_empty_transfer_and_candidates(self):
        rows = batch_rows_to_numpy([torch.empty((0, 6)), torch.empty((0, 6))])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows_to_candidates(rows[0], names={0: "football"}), [])


if __name__ == "__main__":
    unittest.main()
