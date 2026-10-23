"""CPU-only lifecycle contract for the explicitly enabled E04 runtime.

No Ultralytics, TensorRT, CUDA, camera or ROS objects are constructed. The
ordinary predict and candidate conversion entry points remain observable, so
the test checks execution order and ownership rather than pretending to prove
GPU replay correctness or speed.
"""

import copy
import io
import json
import os
import sys
import types
import unittest
from contextlib import ExitStack, contextmanager, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from soccer_perception.adapters.yolo import YoloBallDetector
# Preload these lightweight modules before temporary sys.modules restoration.
# Otherwise a later subtest can patch a stale package attribute while a lazy
# import obtains a freshly loaded registry and escapes the CPU fake.
from soccer_perception import optimizations as _registry
from soccer_perception.adapters import optimization as _legacy


LEGACY_DEFAULTS = {
    "SOCCER_YOLO_POSTPROCESS": "baseline",
    "SOCCER_YOLO_NMS": "torch",
    "SOCCER_YOLO_PREPROCESS": "baseline",
}
VARIANTS = {
    "a2": {"postprocess": "a2", "engine": "b0", "preprocess": "c0"},
    "graph": {"postprocess": "a0", "engine": "graph", "preprocess": "c0"},
    "a2_graph": {"postprocess": "a2", "engine": "graph", "preprocess": "c0"},
}


class FakeHandle:
    def __init__(self, harness, variants):
        self.harness = harness
        self.variants = dict(variants)
        self.restore_errors = []
        self.restore_calls = 0
        self.sync_calls = 0
        self.restored = False
        self.components = {
            key: {"requested": value, "effective": value,
                  "fallback_count": 0, "last_error": None}
            for key, value in variants.items()
        }

    def describe(self):
        return {"requested": dict(self.variants), "restored": self.restored,
                "components": copy.deepcopy(self.components)}

    def synchronize(self):
        self.sync_calls += 1
        self.harness.events.append(("synchronize",))

    def restore(self):
        self.restore_calls += 1
        self.harness.events.append(("restore",))
        if self.restore_errors:
            raise self.restore_errors.pop(0)
        self.restored = True
        self.harness.installed = False


class FakeModel:
    def __init__(self, harness):
        self.harness = harness
        self.names = {0: "football"}
        self.overrides = {"task": "detect"}
        self.callbacks = {}
        self.model = object()
        self.predictor = None
        self.calls = []

    def predict(self, frames, **kwargs):
        self.harness.events.append(("predict", self.harness.installed))
        self.calls.append((frames, kwargs.copy()))
        if self.harness.on_predict is not None:
            self.harness.on_predict(self, frames, kwargs)
        if self.harness.results is not None:
            return self.harness.results
        return [SimpleNamespace(boxes=None, masks=None) for _ in frames]


class Harness:
    def __init__(self):
        self.events = []
        self.installed = False
        self.results = None
        self.on_predict = None
        self.models = []
        self.handles = []
        self.factory = Mock(side_effect=self.make_model)
        self.installer = Mock(side_effect=self.install)
        self.stderr = io.StringIO()

    def make_model(self, *args, **kwargs):
        model = FakeModel(self)
        self.models.append(model)
        return model

    def install(self, detector, variants):
        assert detector.model is self.models[-1]
        assert len(detector.model.calls) == 1, "raw predictor must initialize before hooks"
        self.events.append(("install", dict(variants)))
        self.installed = True
        handle = FakeHandle(self, variants)
        self.handles.append(handle)
        return handle


@contextmanager
def fake_runtime():
    harness = Harness()
    module = types.ModuleType("ultralytics")
    module.YOLO = harness.factory
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {}, clear=True))
        stack.enter_context(patch.dict(sys.modules, {"ultralytics": module}))
        stack.enter_context(patch("soccer_perception.adapters.yolo._install_torchvision_nms_fallback"))
        harness.legacy_selector = stack.enter_context(
            patch.object(_legacy, "experimental_predictor_class", return_value=None))
        stack.enter_context(patch.object(_registry, "install_pipeline", harness.installer))
        # Both a lazy import and a module-level alias can satisfy the API.
        stack.enter_context(patch("soccer_perception.adapters.yolo.install_pipeline",
                                  harness.installer, create=True))
        stack.enter_context(patch.object(YoloBallDetector, "_prepare_model_path",
                                        return_value=Path("frozen.engine")))
        stack.enter_context(redirect_stderr(harness.stderr))
        yield harness


def make_detector(mode="none", **kwargs):
    return YoloBallDetector(Path("frozen.engine"), .45, 640, "0", [0], True,
                            tensorrt=True, trt_batch=2, optimization=mode, **kwargs)


class RuntimeLifecycleTests(unittest.TestCase):
    def test_default_none_has_no_install_or_extra_predict(self):
        with fake_runtime() as h:
            detector = YoloBallDetector(Path("frozen.engine"), .45, 640, "0", [0], True)
            self.assertEqual(detector.optimization, "none")
            self.assertIsNone(detector._optimization_handle)
            detector.load()
            self.assertEqual(len(h.models[0].calls), 0)
            h.installer.assert_not_called()
            self.assertEqual(detector.names, {0: "football"})
            status = detector.optimization_status()
            self.assertEqual(status["mode"], "none")
            self.assertFalse(status["enabled"])
            detector.close()
            self.assertIsNone(detector.model)
            self.assertIsNone(detector._optimization_handle)

    def test_active_modes_initialize_capture_warm_then_synchronize(self):
        for mode, expected in VARIANTS.items():
            with self.subTest(mode=mode), fake_runtime() as h:
                detector = make_detector(mode)
                detector._result_to_candidates = Mock(side_effect=AssertionError("startup result exposed"))
                detector.load()
                detector._result_to_candidates.assert_not_called()
                model = h.models[0]
                handle = h.handles[0]
                h.installer.assert_called_once_with(detector, expected)
                self.assertEqual([event[0] for event in h.events],
                                 ["predict", "install", "predict", "synchronize"])
                self.assertFalse(h.events[0][1])
                self.assertTrue(h.events[2][1])
                self.assertIs(detector._optimization_handle, handle)
                self.assertEqual(handle.sync_calls, 1)
                for frames, kwargs in model.calls:
                    self.assertEqual(len(frames), 2)
                    for frame in frames:
                        self.assertEqual(frame.shape, (640, 640, 3))
                        self.assertEqual(frame.dtype, np.uint8)
                    self.assertEqual(kwargs["conf"], .45)
                    self.assertEqual(kwargs["imgsz"], 640)
                    self.assertEqual(kwargs["classes"], [0])
                    self.assertIs(kwargs["rect"], False)
                    self.assertNotIn("half", kwargs)
                    self.assertNotIn("device", kwargs)
                status = detector.optimization_status()
                self.assertEqual(status["mode"], mode)
                self.assertTrue(status["enabled"])
                self.assertEqual(status["state"]["requested"], expected)
                self.assertIn(mode, h.stderr.getvalue())
                # Startup status is machine-readable, not merely a banner.
                records = []
                for line in h.stderr.getvalue().splitlines():
                    try:
                        records.append(json.loads(line[line.index("{"):]))
                    except ValueError:
                        pass
                self.assertTrue(records, h.stderr.getvalue())
                detector.close()

    def test_each_load_reinitializes_even_for_the_same_engine(self):
        with fake_runtime() as h:
            detector = make_detector("a2_graph")
            paths = [Path("frozen.engine"), Path("frozen.engine"), Path("other.engine")]
            with patch.object(detector, "_prepare_model_path", side_effect=lambda: detector.model_path):
                for index, path in enumerate(paths):
                    with self.subTest(load=index, path=path):
                        detector.model_path = path
                        if index:
                            old_handle = h.handles[-1]
                            previous_factory = h.make_model

                            def create_after_restore(*args, **kwargs):
                                self.assertEqual(old_handle.restore_calls, 1)
                                self.assertIsNone(detector.model)
                                return previous_factory(*args, **kwargs)

                            h.factory.side_effect = create_after_restore
                        detector.load()
                        self.assertEqual(h.factory.call_args.args, (str(path),))
                        self.assertEqual(len(h.models), index + 1)
                        self.assertEqual(len(h.handles), index + 1)
                        self.assertIs(detector.model, h.models[-1])
                        self.assertIs(detector._optimization_handle, h.handles[-1])
                        self.assertEqual(len(h.models[-1].calls), 2)
                        self.assertEqual(h.handles[-1].sync_calls, 1)
                        frames = [np.zeros((8, 8, 3), np.uint8)] * 2
                        self.assertEqual(detector.detect_candidates_batch(frames), [[], []])
                        self.assertEqual(h.installer.call_count, index + 1)
                        self.assertEqual(h.handles[-1].sync_calls, 1)
            detector.close()
            self.assertEqual([handle.restore_calls for handle in h.handles], [1, 1, 1])

    def test_failed_old_graph_cleanup_blocks_reload_before_new_model(self):
        with fake_runtime() as h:
            detector = make_detector("a2_graph")
            detector.load()
            model, handle = detector.model, detector._optimization_handle
            handle.restore_errors = [RuntimeError("old graph cleanup incomplete")]
            with self.assertRaisesRegex(RuntimeError, "old graph cleanup incomplete"):
                detector.load()
            self.assertEqual(h.factory.call_count, 1)
            self.assertEqual(h.installer.call_count, 1)
            self.assertIs(detector.model, model)
            self.assertIs(detector._optimization_handle, handle)
            detector.load()
            self.assertEqual(handle.restore_calls, 2)
            self.assertEqual(h.factory.call_count, 2)
            self.assertIsNot(detector._optimization_handle, handle)
            detector.close()

    def test_real_frames_keep_predict_and_original_candidate_protocol(self):
        for mode in ("none", "a2", "graph", "a2_graph"):
            with self.subTest(mode=mode), fake_runtime() as h:
                detector = make_detector(mode)
                detector.load()
                model = h.models[0]
                before = len(model.calls)
                left, right = object(), object()
                h.results = [left, right]
                left_candidates, right_candidates = [object()], [object(), object()]
                converter = Mock(side_effect=[left_candidates, right_candidates])
                detector._result_to_candidates = converter
                frames = [np.full((5, 7, 3), 17, np.uint8), np.full((5, 7, 3), 83, np.uint8)]
                result = detector.detect_candidates_batch(frames, top_k=5)
                self.assertIs(result[0], left_candidates)
                self.assertIs(result[1], right_candidates)
                self.assertEqual(len(model.calls), before + 1)
                called_frames, kwargs = model.calls[-1]
                for expected, actual in zip(frames, called_frames):
                    self.assertIs(actual, expected)
                self.assertEqual(converter.call_args_list[0].args, (left,))
                self.assertEqual(converter.call_args_list[1].args, (right,))
                self.assertEqual(converter.call_args_list[0].kwargs, {"top_k": 5})
                self.assertEqual(kwargs["conf"], .45)
                self.assertEqual(kwargs["classes"], [0])
                if mode == "none":
                    self.assertNotIn("rect", kwargs)
                else:
                    self.assertIs(kwargs["rect"], False)
                    self.assertEqual(h.handles[0].sync_calls, 1)  # no per-frame sync
                detector.close()

    def test_old_nondefault_environment_rejected_before_yolo_creation(self):
        settings = {"SOCCER_YOLO_POSTPROCESS": "single_class",
                    "SOCCER_YOLO_NMS": "numpy",
                    "SOCCER_YOLO_PREPROCESS": "reuse"}
        for mode in VARIANTS:
            for key, value in settings.items():
                with self.subTest(mode=mode, key=key), fake_runtime() as h:
                    os.environ[key] = value
                    with self.assertRaises(ValueError):
                        make_detector(mode).load()
                    h.factory.assert_not_called()
                    h.installer.assert_not_called()

    def test_explicit_old_defaults_allow_active_mode(self):
        with fake_runtime() as h:
            os.environ.update(LEGACY_DEFAULTS)
            detector = make_detector("a2_graph")
            detector.load()
            self.assertEqual(h.factory.call_count, 1)
            self.assertEqual(h.installer.call_count, 1)
            detector.close()

    def test_none_preserves_legacy_predictor_selection(self):
        with fake_runtime() as h:
            os.environ["SOCCER_YOLO_POSTPROCESS"] = "single_class"
            detector = make_detector()
            detector.load()
            self.assertEqual(h.factory.call_count, 1)
            h.legacy_selector.assert_called_once_with()
            h.installer.assert_not_called()
            self.assertEqual(len(h.models[0].calls), 0)
            detector.close()

    def test_unknown_mode_is_rejected_before_yolo_creation(self):
        for mode in ("a2_grap", "a1", "a3"):
            with self.subTest(mode=mode), fake_runtime() as h:
                with self.assertRaises(ValueError):
                    make_detector(mode).load()
                h.factory.assert_not_called()

    def test_close_restores_before_releasing_model_and_remembers_status(self):
        with fake_runtime() as h:
            detector = make_detector("a2_graph")
            detector.load()
            model, handle = detector.model, detector._optimization_handle
            original_restore = handle.restore

            def check_owner_then_restore():
                self.assertIs(detector.model, model)
                self.assertIs(detector._optimization_handle, handle)
                original_restore()

            handle.restore = check_owner_then_restore
            detector.close()
            self.assertEqual(handle.restore_calls, 1)
            self.assertIsNone(detector.model)
            self.assertIsNone(detector._optimization_handle)
            status = detector.optimization_status()
            self.assertEqual(status["mode"], "a2_graph")
            self.assertFalse(status["enabled"])
            self.assertIsNotNone(status["state"])
            detector.close()
            self.assertEqual(handle.restore_calls, 1)

    def test_failed_restore_preserves_model_and_handle_for_retry(self):
        with fake_runtime() as h:
            detector = make_detector("a2_graph")
            detector.load()
            model, handle = detector.model, detector._optimization_handle
            handle.restore_errors = [RuntimeError("mock outstanding owner")]
            with self.assertRaises(RuntimeError):
                detector.close()
            self.assertIs(detector.model, model)
            self.assertIs(detector._optimization_handle, handle)
            self.assertTrue(detector.optimization_status()["enabled"])
            detector.close()
            self.assertEqual(handle.restore_calls, 2)
            self.assertIsNone(detector.model)
            self.assertIsNone(detector._optimization_handle)

    def test_startup_warm_failure_restores_and_releases_owned_model(self):
        with fake_runtime() as h:
            detector = make_detector("a2_graph")

            def fail_second_call(model, _frames, _kwargs):
                if len(model.calls) == 2:
                    raise RuntimeError("mock optimized startup failure")

            h.on_predict = fail_second_call
            with self.assertRaisesRegex(RuntimeError, "mock optimized startup failure"):
                detector.load()
            self.assertEqual(len(h.models[0].calls), 2)
            self.assertEqual(h.handles[0].restore_calls, 1)
            self.assertIsNone(detector.model)
            self.assertIsNone(detector._optimization_handle)

    def test_startup_install_failure_does_not_leave_model_loaded(self):
        with fake_runtime() as h:
            detector = make_detector("a2_graph")
            h.installer.side_effect = RuntimeError("mock install failure")
            with self.assertRaisesRegex(RuntimeError, "mock install failure"):
                detector.load()
            self.assertEqual(len(h.models[0].calls), 1)
            self.assertIsNone(detector.model)
            self.assertIsNone(detector._optimization_handle)

    def test_startup_capture_fallback_is_visible_before_first_real_frame(self):
        with fake_runtime() as h:
            detector = make_detector("a2_graph")

            def fall_back_during_warm(model, _frames, _kwargs):
                if len(model.calls) == 2:
                    h.handles[0].components["engine"].update(
                        effective="b0", fallback_count=1, last_error="mock capture unavailable")

            h.on_predict = fall_back_during_warm
            detector.load()
            self.assertIn("mock capture unavailable", h.stderr.getvalue())
            self.assertIn("fallback", h.stderr.getvalue().lower())
            self.assertEqual(h.handles[0].sync_calls, 1)
            self.assertEqual(len(h.models[0].calls), 2)
            detector.close()

    def test_close_without_load_is_safe(self):
        detector = make_detector("a2_graph")
        detector.close()
        detector.close()
        self.assertIsNone(detector.model)
        self.assertIsNone(detector._optimization_handle)

    def test_first_runtime_fallback_is_visible_without_retrying_frame(self):
        with fake_runtime() as h:
            detector = make_detector("a2_graph")
            detector.load()
            model, handle = detector.model, detector._optimization_handle
            h.stderr.seek(0)
            h.stderr.truncate(0)
            before = len(model.calls)
            returned = [SimpleNamespace(boxes=None, masks=None), SimpleNamespace(boxes=None, masks=None)]
            h.results = returned

            def graph_fallback(_model, _frames, _kwargs):
                handle.components["engine"].update(effective="b0", fallback_count=1,
                                                  last_error="mock graph fallback")

            h.on_predict = graph_fallback
            frames = [np.zeros((8, 8, 3), np.uint8), np.ones((8, 8, 3), np.uint8)]
            self.assertEqual(detector.detect_candidates_batch(frames, top_k=5), [[], []])
            self.assertEqual(len(model.calls), before + 1)
            self.assertIn("mock graph fallback", h.stderr.getvalue())
            self.assertEqual(handle.sync_calls, 1)
            h.stderr.seek(0)
            h.stderr.truncate(0)
            self.assertEqual(detector.detect_candidates_batch(frames, top_k=5), [[], []])
            self.assertEqual(len(model.calls), before + 2)
            self.assertNotIn("mock graph fallback", h.stderr.getvalue())
            self.assertEqual(detector.optimization_status()["state"]["components"]
                             ["engine"]["fallback_count"], 1)
            detector.close()


if __name__ == "__main__":
    unittest.main()
