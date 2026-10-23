"""Compare optional NMS backends with the unchanged production fallback."""

import ast
import inspect
import unittest

import torch

from soccer_perception.adapters import yolo
from soccer_perception.adapters.nms_backends import dispatch_nms, probe_torchvision_nms


def _production_reference():
    # Compile the existing nested fallback without importing/patching torchvision.
    tree = ast.parse(inspect.getsource(yolo._install_torchvision_nms_fallback))
    node = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "nms_fallback")
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    namespace = {"torch": torch}
    exec(compile(module, "<production nms fallback>", "exec"), namespace)
    return namespace["nms_fallback"]


class NmsBackendTests(unittest.TestCase):
    def setUp(self):
        self.reference = _production_reference()

    def _compare(self, boxes, scores, threshold=0.7, device="cpu"):
        boxes = torch.as_tensor(boxes, dtype=torch.float32, device=device).reshape(-1, 4)
        scores = torch.as_tensor(scores, dtype=torch.float32, device=device)
        expected = self.reference(boxes, scores, threshold)
        for backend in ("torch", "numpy"):
            actual = dispatch_nms(boxes, scores, threshold, backend)
            self.assertEqual(actual.device, boxes.device)
            self.assertEqual(actual.dtype, torch.int64)
            self.assertTrue(torch.equal(actual, expected), (device, backend, threshold, actual, expected))
        return expected

    def test_empty_and_single(self):
        self._compare([], [])
        self._compare([[0, 0, 10, 10]], [0.9])

    def test_overlap_and_decreasing_score_order(self):
        keep = self._compare([[0, 0, 10, 10], [0, 0, 10, 10], [20, 20, 30, 30]], [0.8, 0.9, 0.7])
        self.assertEqual(keep.tolist(), [1, 2])

    def test_equal_scores_preserve_original_device_sort(self):
        self._compare([[i % 4, i % 4, 10 + i % 4, 10 + i % 4] for i in range(64)], [0.5] * 64)

    def test_threshold_equality_kept_and_greater_suppressed(self):
        boxes = [[0, 0, 2, 2], [0, 0, 1, 2]]  # exact IoU 0.5
        self.assertEqual(self._compare(boxes, [0.9, 0.8], 0.5).tolist(), [0, 1])
        self.assertEqual(self._compare(boxes, [0.9, 0.8], 0.499).tolist(), [0])
        self._compare(boxes, [0.9, 0.8], 0)
        self._compare(boxes, [0.9, 0.8], 1)

    def test_zero_negative_area_and_nonfinite(self):
        self._compare([[0, 0, 0, 1], [0, 0, 0, 1], [2, 2, 1, 1], [0, 0, 10, 10]], [0.9, 0.8, 0.7, 0.6])
        self._compare([[float("nan"), 0, 1, 1], [0, 0, float("inf"), 1], [0, 0, 1, 1]], [0.9, 0.8, 0.7])
        self._compare([[0, 0, 1, 1], [0, 0, 1, 1]], [float("nan"), 0.5])

    def test_randomized_including_score_ties_and_invalid_boxes(self):
        generator = torch.Generator().manual_seed(20261020)
        for size in (2, 7, 32, 128, 301):
            for threshold in (0., 0.3, 0.7, 1.):
                xy = torch.rand(size, 2, generator=generator) * 200
                wh = torch.randn(size, 2, generator=generator) * 50
                boxes = torch.cat((xy, xy + wh), 1)
                scores = torch.randint(0, 8, (size,), generator=generator).float() / 8
                self._compare(boxes, scores, threshold)

    def test_numpy_rejects_unvalidated_dtype_and_unknown_backend(self):
        with self.assertRaises(TypeError):
            dispatch_nms(torch.zeros(1, 4, dtype=torch.float16), torch.ones(1, dtype=torch.float16), .7, "numpy")
        with self.assertRaises(ValueError):
            dispatch_nms(torch.zeros(1, 4), torch.ones(1), .7, "unknown")

    def test_torchvision_probe_and_valid_distinct_scores(self):
        capability = probe_torchvision_nms("cpu")
        if not capability["available"]:
            self.skipTest(capability.get("error", "torchvision custom op unavailable"))
        boxes = torch.tensor([[0., 0., 10., 10.], [1., 1., 11., 11.], [20., 20., 30., 30.]])
        scores = torch.tensor([.9, .8, .7])
        self.assertTrue(torch.equal(self.reference(boxes, scores, .7), dispatch_nms(boxes, scores, .7, "torchvision")))

    @unittest.skipUnless(torch.cuda.is_available(), "CUDA device unavailable")
    def test_cuda_ties_and_copy_boundary(self):
        self._compare([[i % 4, i % 4, 10 + i % 4, 10 + i % 4] for i in range(64)], [0.5] * 64, device="cuda:0")
        self._compare([[0, 0, 0, 1], [0, 0, 0, 1], [2, 2, 1, 1]], [.9, .8, .7], device="cuda:0")


if __name__ == "__main__":
    unittest.main()
