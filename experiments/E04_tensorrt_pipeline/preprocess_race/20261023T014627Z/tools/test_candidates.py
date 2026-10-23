"""CPU correctness against the exact robot Ultralytics source, no model load."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import tarfile
import types
from typing import List, Union
import unittest
from unittest import mock

import cv2
import numpy as np
import torch

from candidates import install


ROOT = next(p for p in Path(__file__).resolve().parents if (p / "frozen.json").is_file())
VAL_ROOT = ROOT.parents[1] / "runs" / "20261022T020842Z_78f1b7" / "val_cases"


def reference_predictor_class():
    """Execute only image LetterBox and two audited predictor methods."""
    namespace = {"cv2": cv2, "np": np, "torch": torch, "Union": Union, "List": List}
    augment = ast.parse((ROOT / "audit/library/data/augment.py").read_text())
    letterbox = next(node for node in augment.body if isinstance(node, ast.ClassDef)
                     and node.name == "LetterBox")
    exec(compile(ast.Module(body=[letterbox], type_ignores=[]), "robot/augment.py", "exec"), namespace)
    predictor = ast.parse((ROOT / "audit/library/engine/predictor.py").read_text())
    base = next(node for node in predictor.body if isinstance(node, ast.ClassDef)
                and node.name == "BasePredictor")
    methods = [node for node in base.body if isinstance(node, ast.FunctionDef)
               and node.name in ("preprocess", "pre_transform")]
    reduced = ast.ClassDef(name="ReferencePredictor", bases=[], keywords=[], body=methods, decorator_list=[])
    ast.fix_missing_locations(reduced)
    exec(compile(ast.Module(body=[reduced], type_ignores=[]), "robot/predictor.py", "exec"), namespace)
    return namespace["ReferencePredictor"]


ReferencePredictor = reference_predictor_class()


def predictor():
    result = ReferencePredictor()
    result.args = types.SimpleNamespace(rect=False)
    result.model = types.SimpleNamespace(pt=False, dynamic=False, imx=False, stride=32, fp16=False)
    result.imgsz = [640, 640]
    result.device = torch.device("cpu")
    return result


class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        self.rng = np.random.default_rng(20261023)

    def images(self, shape=(376, 672)):
        return [self.rng.integers(0, 256, shape + (3,), dtype=np.uint8) for _ in range(2)]

    def test_exact_rounding_padding_channel_and_stereo_pixels(self):
        for variant in ("canvas", "reuse"):
            for shape in ((376, 672), (377, 671), (672, 376), (640, 640), (95, 127), (11, 13)):
                with self.subTest(variant=variant, shape=shape):
                    images = self.images(shape)
                    snapshots = [image.copy() for image in images]
                    expected = predictor().preprocess(images)
                    active = predictor()
                    handle = install(active, variant)
                    actual = active.preprocess(im=images)
                    self.assertTrue(torch.equal(expected, actual))
                    self.assertFalse(torch.equal(actual[0], actual[1]))
                    for image, snapshot in zip(images, snapshots):
                        np.testing.assert_array_equal(image, snapshot)
                    self.assertEqual(handle.describe()["success_count"], 1)
                    self.assertEqual(handle.describe()["fallback_count"], 0)
                    handle.restore()

    def test_repeated_changed_images_and_retained_outputs(self):
        for variant in ("canvas", "reuse"):
            active = predictor()
            handle = install(active, variant)
            images = self.images()
            first = active.preprocess(images)
            snapshot = first.clone()
            second_images = [np.zeros_like(images[0]), np.full_like(images[1], 255)]
            second = active.preprocess(second_images)
            self.assertTrue(torch.equal(first, snapshot), variant)
            self.assertNotEqual(first.data_ptr(), second.data_ptr())
            self.assertTrue(torch.equal(second, predictor().preprocess(second_images)))
            state = handle.describe()
            self.assertEqual((state["calls"], state["success_count"], state["fallback_count"]), (2, 2, 0))
            self.assertEqual(state["canvas_allocations"], 2 if variant == "canvas" else 1)
            self.assertEqual(state["host_buffer_allocations"], 0 if variant == "canvas" else 1)
            self.assertEqual(state["host_tensor_view_allocations"], 0 if variant == "canvas" else 1)
            self.assertEqual(state["fp32_output_allocations"], None if variant == "canvas" else 2)
            self.assertFalse(state["gpu_output_buffer_reused"])
            handle.restore()

    def test_noncontiguous_readonly_inputs(self):
        images = [image[:, ::-1] for image in self.images()]
        for image in images:
            image.flags.writeable = False
        expected = predictor().preprocess(images)
        for variant in ("canvas", "reuse"):
            active = predictor()
            handle = install(active, variant)
            self.assertTrue(torch.equal(active.preprocess(images), expected))
            self.assertEqual(handle.describe()["fallback_count"], 0)
            handle.restore()

    def test_shape_change_falls_back_without_poisoning_frozen_buffers(self):
        for variant in ("canvas", "reuse"):
            active = predictor()
            handle = install(active, variant)
            original_images = self.images()
            active.preprocess(original_images)
            changed = self.images((672, 376))
            self.assertTrue(torch.equal(active.preprocess(changed), predictor().preprocess(changed)))
            self.assertEqual(handle.describe()["fallback_count"], 1)
            self.assertIn("shape changed", handle.describe()["last_error"])
            self.assertTrue(torch.equal(active.preprocess(original_images), predictor().preprocess(original_images)))
            self.assertEqual(handle.describe()["success_count"], 2)
            handle.restore()

    def test_unsupported_dtype_batch_and_backend_use_saved_original(self):
        for variant in ("canvas", "reuse"):
            cases = [([self.images()[0]], None),
                     ([image.astype(np.float32) for image in self.images()], None),
                     (self.images(), ("fp16", True)),
                     (self.images(), ("dynamic", True)),
                     (self.images(), ("pt", True))]
            for images, change in cases:
                with self.subTest(variant=variant, change=change, length=len(images)):
                    active = predictor()
                    baseline = predictor()
                    if change:
                        setattr(active.model, *change)
                        setattr(baseline.model, *change)
                    expected = baseline.preprocess(images)
                    handle = install(active, variant)
                    self.assertTrue(torch.equal(active.preprocess(images), expected))
                    self.assertEqual(handle.describe()["fallback_count"], 1)
                    self.assertEqual(handle.describe()["success_count"], 0)
                    handle.restore()

    def test_exception_falls_back_and_restore_is_unconditional_and_idempotent(self):
        for variant in ("canvas", "reuse"):
            active = predictor()
            handle = install(active, variant)
            method = "_canvas" if variant == "canvas" else "_reuse"
            images = self.images()
            with mock.patch.object(handle, method, side_effect=ValueError("injected failure")):
                self.assertTrue(torch.equal(active.preprocess(images), predictor().preprocess(images)))
            self.assertEqual(handle.describe()["fallback_count"], 1)
            self.assertIn("injected failure", handle.describe()["last_error"])
            with self.assertRaises(ValueError):
                install(active, variant)
            hook = "pre_transform" if variant == "canvas" else "preprocess"
            setattr(active, hook, lambda im: None)
            handle.restore()
            handle.restore()
            self.assertNotIn(hook, vars(active))
            self.assertTrue(torch.equal(active.preprocess(images), predictor().preprocess(images)))
            self.assertEqual(handle.describe()["restore_count"], 1)
            self.assertTrue(handle.describe()["restored"])

    def test_restore_preserves_preexisting_instance_override(self):
        for variant in ("canvas", "reuse"):
            active = predictor()
            hook = "pre_transform" if variant == "canvas" else "preprocess"
            original = getattr(active, hook)
            setattr(active, hook, original)
            handle = install(active, variant)
            handle.restore()
            self.assertIs(vars(active)[hook], original)

    def test_canvas_only_changes_pre_transform(self):
        active = predictor()
        handle = install(active, "canvas")
        self.assertNotIn("preprocess", vars(active))
        images = self.images()
        borrowed = active.pre_transform(im=images)
        self.assertFalse(np.shares_memory(borrowed[0], borrowed[1]))
        self.assertEqual(handle.describe()["hook"], "pre_transform")
        handle.restore()

    def test_61_fixed_val_pairs_exactly_match_audited_preprocess(self):
        cases = json.loads((VAL_ROOT / "cases.json").read_text())
        self.assertEqual(cases["split"], "val")
        self.assertFalse(cases["test_accessed"])
        self.assertEqual(len(cases["pairs"]), 61)
        active = {variant: predictor() for variant in ("canvas", "reuse")}
        handles = {variant: install(value, variant) for variant, value in active.items()}
        with tarfile.open(VAL_ROOT / "val_cases.tar.gz") as archive:
            members = {Path(member.name).name: member for member in archive.getmembers() if member.isfile()}
            for case in cases["pairs"]:
                images = [cv2.imdecode(np.frombuffer(archive.extractfile(members[case[key]]).read(), np.uint8),
                                      cv2.IMREAD_COLOR) for key in ("left", "right")]
                self.assertTrue(all(image is not None for image in images))
                expected = predictor().preprocess(images)
                for variant in active:
                    self.assertTrue(torch.equal(active[variant].preprocess(images), expected),
                                    "%s %s" % (variant, case["pair_key"]))
        for variant, handle in handles.items():
            self.assertEqual(handle.describe()["success_count"], 61)
            self.assertEqual(handle.describe()["fallback_count"], 0)
            handle.restore()


if __name__ == "__main__":
    unittest.main()
