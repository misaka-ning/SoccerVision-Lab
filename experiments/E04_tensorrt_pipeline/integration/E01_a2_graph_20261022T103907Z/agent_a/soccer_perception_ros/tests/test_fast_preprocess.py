"""Compare P4 against real Ultralytics LetterBox and frozen robot inputs."""

import ast
import os
from pathlib import Path
import tarfile
import types
import unittest

import cv2
import numpy as np
import torch

from soccer_perception.adapters.fast_preprocess import ReusablePreprocessor


def reference_letterbox():
    archive = os.environ.get("E02_ULTRALYTICS_SOURCE_ARCHIVE")
    if not archive:
        from ultralytics.data.augment import LetterBox
        return LetterBox
    with tarfile.open(archive) as source_archive:
        source = source_archive.extractfile("ultralytics/data/augment.py").read().decode()
    node = next(node for node in ast.parse(source).body
                if isinstance(node, ast.ClassDef) and node.name == "LetterBox")
    namespace = {"cv2": cv2, "np": np}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<deployed LetterBox>", "exec"), namespace)
    return namespace["LetterBox"]


def reference_uint8(images, shape, **kwargs):
    transform = reference_letterbox()(shape, **kwargs)
    return np.ascontiguousarray(
        np.stack([transform(image=image) for image in images])[..., ::-1].transpose(0, 3, 1, 2)
    )


class FastPreprocessTests(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(7103)
        self.preprocessor = ReusablePreprocessor()

    def image(self, height, width):
        return self.rng.integers(0, 256, (height, width, 3), dtype=np.uint8)

    def test_letterbox_matches_deployed_cv2_pixels_across_rounding_cases(self):
        for shape in [(376, 672), (377, 671), (672, 376), (640, 640), (95, 127), (11, 13)]:
            for target in [640, (512, 640)]:
                for kwargs in [dict(auto=False), dict(auto=True), dict(scaleup=False),
                               dict(scale_fill=True), dict(center=False),
                               dict(auto=True, center=False, stride=64)]:
                    with self.subTest(shape=shape, target=target, kwargs=kwargs):
                        images = [self.image(*shape), self.image(*shape)]
                        expected = reference_uint8(images, target, **kwargs)
                        actual = self.preprocessor.prepare_uint8(images, target, **kwargs)
                        np.testing.assert_array_equal(actual, expected)
                        self.assertTrue(actual.flags.c_contiguous)

    def test_stereo_order_channel_order_and_padding(self):
        left, right = np.empty((376, 672, 3), np.uint8), np.empty((376, 672, 3), np.uint8)
        left[:] = (7, 19, 239)
        right[:] = (211, 23, 11)
        actual = self.preprocessor.prepare_uint8([left, right], 640)
        np.testing.assert_array_equal(actual[0, :, 200, 300], (239, 19, 7))
        np.testing.assert_array_equal(actual[1, :, 200, 300], (11, 23, 211))
        np.testing.assert_array_equal(actual[:, :, 0, 0], np.full((2, 3), 114))

    def test_noncontiguous_and_mixed_shapes_do_not_mutate_source(self):
        left = self.image(376, 1344)[:, ::2]
        right = self.image(751, 641)[::-1]
        snapshots = [left.copy(), right.copy()]
        expected = reference_uint8([left, right], 640)
        actual = self.preprocessor.prepare_uint8([left, right], 640)
        np.testing.assert_array_equal(actual, expected)
        for image, snapshot in zip([left, right], snapshots):
            np.testing.assert_array_equal(image, snapshot)

    def test_reuse_and_shape_changes_have_no_stale_padding(self):
        for shape in [(376, 672), (376, 672), (672, 376), (376, 672)]:
            images = [self.image(*shape), self.image(*shape)]
            actual = self.preprocessor.prepare_uint8(images, 640)
            np.testing.assert_array_equal(actual, reference_uint8(images, 640))
        batch = self.preprocessor._batch
        canvas = self.preprocessor._canvas
        self.preprocessor.prepare_uint8(images, 640)
        self.assertIs(batch, self.preprocessor._batch)
        self.assertIs(canvas, self.preprocessor._canvas)

    def test_float32_and_float16_match_original_tensor_normalization(self):
        images = [self.image(376, 672), self.image(376, 672)]
        for fp16 in [False, True]:
            reference = torch.from_numpy(reference_uint8(images, 640))
            reference = reference.half() if fp16 else reference.float()
            reference /= 255
            actual = self.preprocessor.preprocess(images, 640, device="cpu", fp16=fp16)
            self.assertTrue(torch.equal(actual, reference))
            pointer = actual.data_ptr()
            again = self.preprocessor.preprocess(images, 640, device="cpu", fp16=fp16)
            self.assertEqual(pointer, again.data_ptr())
            self.assertTrue(torch.equal(again, reference))

    def test_predictor_hook_uses_original_auto_rule(self):
        images = [self.image(376, 672), self.image(376, 672)]
        for pt, dynamic, imx, rect in [(False, False, False, True),
                                        (True, False, False, True),
                                        (False, True, False, True),
                                        (False, True, True, True),
                                        (True, False, False, False)]:
            predictor = types.SimpleNamespace(
                args=types.SimpleNamespace(rect=rect), imgsz=(640, 640), device="cpu",
                model=types.SimpleNamespace(pt=pt, dynamic=dynamic, imx=imx, stride=32, fp16=False),
            )
            actual = self.preprocessor.for_predictor(predictor, images)
            expected = torch.from_numpy(reference_uint8(
                images, (640, 640), auto=rect and (pt or (dynamic and not imx)), stride=32
            )).float() / 255
            self.assertTrue(torch.equal(actual, expected))

    def test_unsupported_inputs_can_use_original_predictor(self):
        for images in [[], None, torch.zeros(2, 3, 10, 10), np.zeros((2, 10, 10, 3)),
                       [np.zeros((10, 10, 4), np.uint8)], [np.zeros((10, 10, 3), np.float32)]]:
            self.assertFalse(self.preprocessor.supports(images))

    def test_frozen_robot_images(self):
        directory = os.environ.get("E02_GOLDEN_DIR")
        if not directory:
            self.skipTest("E02_GOLDEN_DIR not supplied")
        paths = sorted(Path(directory).glob("frame_*.npz"))
        if not paths:
            self.skipTest("Frozen robot images have not been downloaded")
        for path in paths:
            with np.load(path) as sample:
                images = [sample["left"], sample["right"]]
                expected = torch.from_numpy(reference_uint8(images, 640)).float() / 255
                actual = self.preprocessor.preprocess(images, 640, device="cpu")
                self.assertTrue(torch.equal(actual, expected), str(path))
        # CPU/CUDA division has a one-ULP arithmetic difference. The resize and
        # packing comparison above is exact; do not hide image differences in a
        # loose tolerance. A separate CUDA test checks the deployed tensor.
        original_tensor = Path(directory) / "preprocessed.npy"
        first_frame = Path(directory) / "frame_000.npz"
        if original_tensor.exists() and first_frame.exists():
            with np.load(first_frame) as sample:
                actual = self.preprocessor.preprocess(
                    [sample["left"], sample["right"]], 640, device="cpu"
                ).numpy()
            np.testing.assert_allclose(actual, np.load(original_tensor), rtol=0, atol=6e-8)

    @unittest.skipUnless(torch.cuda.is_available(), "CUDA unavailable")
    def test_cuda_transfer_and_normalization_match_original(self):
        images = [self.image(376, 672), self.image(376, 672)]
        for fp16 in [False, True]:
            expected = torch.from_numpy(reference_uint8(images, 640)).to("cuda:0")
            expected = expected.half() if fp16 else expected.float()
            expected /= 255
            actual = self.preprocessor.preprocess(images, 640, device="cuda:0", fp16=fp16)
            self.assertTrue(torch.equal(actual, expected))
        directory = os.environ.get("E02_GOLDEN_DIR")
        if directory and (Path(directory) / "preprocessed.npy").exists():
            with np.load(Path(directory) / "frame_000.npz") as sample:
                actual = self.preprocessor.preprocess(
                    [sample["left"], sample["right"]], 640, device="cuda:0"
                )
            golden = torch.from_numpy(np.load(Path(directory) / "preprocessed.npy")).to("cuda:0")
            self.assertTrue(torch.equal(actual, golden))


if __name__ == "__main__":
    unittest.main()
