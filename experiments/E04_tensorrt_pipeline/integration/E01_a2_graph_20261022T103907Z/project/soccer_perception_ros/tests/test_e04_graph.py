"""CPU-only contract/state tests. Mock capture is NOT CUDA validation."""

import contextlib
import sys
import types
import unittest
from unittest import mock

from soccer_perception.optimizations import graph


class FakeDevice:
    type = "cuda"

    def __str__(self):
        return "cuda:0"


DEVICE = FakeDevice()


class FakeTensor:
    next_pointer = 100
    pointers = {}

    def __init__(self, shape, value=0, dtype="float32", device=DEVICE):
        self.shape = shape
        self.dtype = dtype
        self.device = device
        self.value = value
        self.pointer = FakeTensor.next_pointer
        FakeTensor.next_pointer += 1
        FakeTensor.pointers[self.pointer] = self
        self.recorded = []

    def data_ptr(self):
        return self.pointer

    def is_contiguous(self):
        return True

    def copy_(self, other, non_blocking=False):
        self.value = other.value
        return self

    def record_stream(self, stream):
        self.recorded.append(stream)

    def clone(self):
        return FakeTensor(self.shape, self.value, self.dtype, self.device)


class FakeStream:
    next_id = 1

    def __init__(self, device=DEVICE):
        self.cuda_stream = FakeStream.next_id
        FakeStream.next_id += 1
        self.waits = []
        self.syncs = 0

    def wait_stream(self, other):
        self.waits.append(other)

    def synchronize(self):
        self.syncs += 1


class FakeCudaGraph:
    def __init__(self):
        self.call = None

    def replay(self):
        self.call()


class FakeCuda:
    def __init__(self):
        self.caller = FakeStream()
        self.active_capture = None

    def is_available(self):
        return True

    Stream = FakeStream
    CUDAGraph = FakeCudaGraph

    def current_stream(self, device=None):
        return self.caller

    @contextlib.contextmanager
    def stream(self, stream):
        yield

    @contextlib.contextmanager
    def device(self, device):
        yield

    @contextlib.contextmanager
    def graph(self, obj, stream=None):
        self.active_capture = obj
        try:
            yield
        finally:
            self.active_capture = None


class FakeTorch:
    float32 = "float32"

    def __init__(self):
        self.cuda = FakeCuda()

    def empty(self, shape, dtype=None, device=None):
        return FakeTensor(shape, dtype=dtype, device=device)


class FakeContext:
    def __init__(self, torch):
        self.torch = torch
        self.calls = 0
        self.fail_enqueue = False

    def execute_async_v2(self, bindings, stream_handle):
        self.calls += 1
        if self.fail_enqueue:
            return False

        def execute():
            inp, out = [FakeTensor.pointers[pointer] for pointer in bindings]
            out.value = inp.value * 2

        if self.torch.cuda.active_capture is not None:
            self.torch.cuda.active_capture.call = execute
        else:
            execute()
        return True


class FakeEngine:
    has_implicit_batch_dimension = False
    num_bindings = 2

    def __init__(self, torch):
        self.torch = torch
        self.contexts = []

    def get_binding_name(self, index):
        return ["images", "output0"][index]

    def binding_is_input(self, index):
        return index == 0

    def get_binding_shape(self, index):
        return [graph.INPUT_SHAPE, graph.OUTPUT_SHAPE][index]

    def is_shape_binding(self, index):
        return False

    def create_execution_context(self):
        context = FakeContext(self.torch)
        self.contexts.append(context)
        return context


class FakeBackend:
    engine = True
    dynamic = False
    is_trt10 = False
    fp16 = False
    nhwc = False
    output_names = ["output0"]

    def __init__(self, torch):
        self.model = FakeEngine(torch)
        self.context = object()
        self.binding_addrs = {"images": 10, "output0": 11}
        self.baseline_calls = []
        self.bindings = {}
        for name, shape in [("images", graph.INPUT_SHAPE), ("output0", graph.OUTPUT_SHAPE)]:
            self.bindings[name] = types.SimpleNamespace(shape=shape, data=FakeTensor(shape))

    def forward(self, im, *args, **kwargs):
        self.baseline_calls.append((im, args, kwargs))
        return "baseline"


def detector_for(backend):
    return types.SimpleNamespace(model=types.SimpleNamespace(predictor=types.SimpleNamespace(model=backend)))


class GraphContractTests(unittest.TestCase):
    def setUp(self):
        self.torch = FakeTorch()
        self.backend = FakeBackend(self.torch)
        self.detector = detector_for(self.backend)
        self.patch = mock.patch.dict(sys.modules, {"torch": self.torch})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_b0_does_not_patch_or_allocate(self):
        handle = graph.install(self.detector, "b0")
        self.assertNotIn("forward", self.backend.__dict__)
        self.assertEqual(self.backend.forward(None), "baseline")
        self.assertEqual(handle.describe()["effective"], "b0")
        self.assertEqual(self.backend.model.contexts, [])
        handle.restore()

    def test_mock_changed_inputs_replay_current_data_and_own_output(self):
        context = self.backend.context
        addresses = self.backend.binding_addrs.copy()
        handle = graph.install(self.detector, "graph")
        self.addCleanup(handle.restore)
        self.assertEqual(handle.describe()["effective"], "pending_capture")
        first = self.backend.forward(FakeTensor(graph.INPUT_SHAPE, 3))
        self.assertEqual(first.value, 6)
        first.value = -100  # NMS's permitted in-place mutation of returned storage.
        second = self.backend.forward(FakeTensor(graph.INPUT_SHAPE, 7))
        self.assertEqual(second.value, 14)
        self.assertEqual(first.value, -100)
        self.assertIs(self.backend.context, context)
        self.assertEqual(self.backend.binding_addrs, addresses)
        status = handle.describe()
        self.assertEqual(status["capture_count"], 1)
        self.assertEqual(status["replay_count"], 2)
        self.assertEqual(status["input_update_count"], 2)
        self.assertEqual(status["warmup_enqueue_count"], 3)
        self.assertEqual(status["output_clone_count"], 2)
        self.assertEqual(status["fallback_count"], 0)
        runner = handle._runner
        self.assertEqual(runner.stream.waits, [self.torch.cuda.caller] * 3)
        self.assertEqual(self.torch.cuda.caller.waits, [runner.stream] * 2)
        self.assertEqual(len(self.backend.model.contexts), 1)

    def test_restore_releases_owned_allocations_and_exact_method(self):
        handle = graph.install(self.detector, "graph")
        self.backend.forward(FakeTensor(graph.INPUT_SHAPE, 2))
        handle.synchronize()
        handle.restore()
        handle.restore()
        self.assertNotIn("forward", self.backend.__dict__)
        self.assertNotIn("_e04_graph_handle", self.backend.__dict__)
        status = handle.describe()
        self.assertEqual(status["effective"], "restored")
        self.assertEqual(status["replay_count"], 1)
        for key in ("private_context_allocated", "graph_allocated", "stream_allocated", "buffers_allocated"):
            self.assertFalse(status[key])

    def test_instance_override_restored_exactly(self):
        override = lambda im: "custom baseline"
        self.backend.forward = override
        handle = graph.install(self.detector, "graph")
        handle.restore()
        self.assertIs(self.backend.forward, override)

    def test_restore_can_retry_cleanup_without_repatching_baseline(self):
        handle = graph.install(self.detector, "graph")
        self.backend.forward(FakeTensor(graph.INPUT_SHAPE, 2))
        runner = handle._runner
        with mock.patch.object(runner, "synchronize", side_effect=RuntimeError("temporary sync failure")):
            with self.assertRaises(graph.GraphExecutionError):
                handle.restore()
        self.assertNotIn("forward", self.backend.__dict__)
        self.assertTrue(handle.describe()["buffers_allocated"])
        handle.restore()
        self.assertFalse(handle.describe()["buffers_allocated"])
        self.assertEqual(self.backend.forward(None), "baseline")

    def test_unsupported_backend_fails_before_context_allocation(self):
        self.backend.dynamic = True
        handle = graph.install(self.detector, "graph")
        self.addCleanup(handle.restore)
        self.assertEqual(self.backend.forward(FakeTensor(graph.INPUT_SHAPE, 2)), "baseline")
        self.assertEqual(self.backend.model.contexts, [])
        self.assertEqual(handle.describe()["effective"], "b0")
        self.assertIn("static TensorRT", handle.describe()["last_error"])

    def test_input_mismatch_disables_and_preserves_original_arguments(self):
        handle = graph.install(self.detector, "graph")
        self.addCleanup(handle.restore)
        wrong = FakeTensor((1, 3, 640, 640), 1)
        self.assertEqual(self.backend.forward(wrong), "baseline")
        self.assertEqual(handle.describe()["effective"], "b0")
        self.assertIn("shape", handle.describe()["disabled_reason"])
        current = FakeTensor(graph.INPUT_SHAPE, 2)
        self.assertEqual(self.backend.forward(current, augment=True), "baseline")
        self.assertEqual(self.backend.baseline_calls[-1], (current, (), {"augment": True}))
        self.assertEqual(handle.describe()["fallback_count"], 2)

    def test_capture_failure_closes_owned_context_and_baseline_survives(self):
        handle = graph.install(self.detector, "graph")
        self.addCleanup(handle.restore)
        with mock.patch.object(self.torch.cuda, "CUDAGraph", side_effect=RuntimeError("capture unsupported")):
            self.assertEqual(self.backend.forward(FakeTensor(graph.INPUT_SHAPE, 1)), "baseline")
        status = handle.describe()
        self.assertEqual(status["effective"], "b0")
        self.assertIn("capture unsupported", status["last_error"])
        self.assertEqual(status["warmup_enqueue_count"], 3)
        self.assertFalse(status["buffers_allocated"])
        self.assertEqual(len(self.backend.baseline_calls), 1)

    def test_trt_false_return_does_not_report_graph_success(self):
        handle = graph.install(self.detector, "graph")
        self.addCleanup(handle.restore)
        with mock.patch.object(FakeContext, "execute_async_v2", return_value=False):
            self.assertEqual(self.backend.forward(FakeTensor(graph.INPUT_SHAPE, 1)), "baseline")
        status = handle.describe()
        self.assertEqual(status["capture_count"], 0)
        self.assertEqual(status["replay_count"], 0)
        self.assertIn("returned false", status["last_error"])

    def test_replay_failure_does_not_reuse_old_output(self):
        handle = graph.install(self.detector, "graph")
        self.addCleanup(handle.restore)
        self.backend.forward(FakeTensor(graph.INPUT_SHAPE, 1))
        with mock.patch.object(handle._runner.graph, "replay", side_effect=RuntimeError("replay failed")):
            self.assertEqual(self.backend.forward(FakeTensor(graph.INPUT_SHAPE, 5)), "baseline")
        self.assertEqual(handle.describe()["replay_count"], 1)
        self.assertEqual(handle.describe()["input_update_count"], 2)
        self.assertEqual(handle.describe()["fallback_count"], 1)

    def test_async_failure_is_visible_and_never_returns_a_frame(self):
        handle = graph.install(self.detector, "graph")
        self.backend.forward(FakeTensor(graph.INPUT_SHAPE, 1))
        runner = handle._runner
        with mock.patch.object(runner, "synchronize", side_effect=RuntimeError("device lost")):
            with self.assertRaises(graph.GraphExecutionError):
                handle.synchronize()
        self.assertEqual(len(self.backend.baseline_calls), 0)
        self.assertIn("device lost", handle.describe()["cleanup_error"])
        # Once fake CUDA recovers, restore can safely release owned allocations.
        handle.restore()

    def test_duplicate_and_invalid_install_fail_before_mutation(self):
        with self.assertRaises(ValueError):
            graph.install(self.detector, "fastest")
        with self.assertRaises(ValueError):
            graph.install(types.SimpleNamespace(), "graph")
        handle = graph.install(self.detector, "graph")
        self.addCleanup(handle.restore)
        with self.assertRaises(RuntimeError):
            graph.install(self.detector, "graph")

    def test_install_requires_predictor_backend_to_be_ready(self):
        for model in (None, types.SimpleNamespace(predictor=None),
                      types.SimpleNamespace(predictor=types.SimpleNamespace(model=None))):
            with self.subTest(model=model):
                with self.assertRaisesRegex(ValueError, "Initialize detector"):
                    graph.install(types.SimpleNamespace(model=model), "graph")
        self.assertNotIn("forward", self.backend.__dict__)
        self.assertEqual(self.backend.model.contexts, [])

    def test_close_before_first_frame_does_not_allocate_or_capture(self):
        handle = graph.install(self.detector, "graph")
        status = handle.describe()
        self.assertEqual(status["effective"], "pending_capture")
        self.assertEqual(status["calls"], 0)
        self.assertEqual(status["capture_count"], 0)
        self.assertFalse(status["buffers_allocated"])
        handle.restore()
        handle.restore()
        self.assertEqual(self.backend.model.contexts, [])
        self.assertNotIn("_e04_graph_handle", self.backend.__dict__)
        self.assertEqual(self.backend.forward(None), "baseline")

    def test_ordinary_predictor_keywords_capture_once_for_current_frames(self):
        handle = graph.install(self.detector, "graph")
        self.addCleanup(handle.restore)
        for value in (3, 7, 11):
            result = self.backend.forward(FakeTensor(graph.INPUT_SHAPE, value),
                                          augment=False, visualize=False, embed=None)
            self.assertEqual(result.value, value * 2)
        status = handle.describe()
        self.assertEqual(status["capture_count"], 1)
        self.assertEqual(status["replay_count"], 3)
        self.assertEqual(status["input_update_count"], 3)
        self.assertEqual(status["output_clone_count"], 3)
        self.assertEqual(status["fallback_count"], 0)

    def test_restore_then_reinstall_owns_fresh_context_and_statistics(self):
        first = graph.install(self.detector, "graph")
        retained_output = self.backend.forward(FakeTensor(graph.INPUT_SHAPE, 3))
        old_context = first._runner.context
        first.restore()
        second = graph.install(self.detector, "graph")
        self.addCleanup(second.restore)
        self.assertEqual(second.describe()["effective"], "pending_capture")
        self.assertEqual(second.describe()["calls"], 0)
        result = self.backend.forward(FakeTensor(graph.INPUT_SHAPE, 9))
        self.assertEqual(result.value, 18)
        self.assertEqual(retained_output.value, 6)
        self.assertIsNot(second._runner.context, old_context)
        self.assertEqual(len(self.backend.model.contexts), 2)
        self.assertEqual(second.describe()["capture_count"], 1)
        self.assertEqual(second.describe()["replay_count"], 1)
        first.restore()  # A stale, fully closed handle cannot remove the new patch.
        self.assertIs(self.backend._e04_graph_handle, second)
        self.assertIs(self.backend.forward, second._replacement)

    def test_old_backend_cleanup_does_not_unpatch_reloaded_backend(self):
        old_backend = self.backend
        old_handle = graph.install(self.detector, "graph")
        old_backend.forward(FakeTensor(graph.INPUT_SHAPE, 3))
        new_backend = FakeBackend(self.torch)
        self.detector.model.predictor.model = new_backend
        new_handle = graph.install(self.detector, "graph")
        self.addCleanup(new_handle.restore)
        old_handle.restore()
        self.assertNotIn("forward", old_backend.__dict__)
        self.assertIs(new_backend._e04_graph_handle, new_handle)
        self.assertEqual(new_backend.forward(FakeTensor(graph.INPUT_SHAPE, 7)).value, 14)
        self.assertEqual(new_handle.describe()["fallback_count"], 0)

    def test_startup_context_creation_failure_releases_partial_allocations(self):
        handle = graph.install(self.detector, "graph")
        self.addCleanup(handle.restore)
        current = FakeTensor(graph.INPUT_SHAPE, 5)
        with mock.patch.object(self.backend.model, "create_execution_context", return_value=None):
            self.assertEqual(self.backend.forward(current), "baseline")
        status = handle.describe()
        self.assertEqual(status["effective"], "b0")
        self.assertIn("independent TensorRT execution context", status["disabled_reason"])
        self.assertEqual(status["capture_count"], 0)
        self.assertEqual(status["fallback_count"], 1)
        self.assertEqual(self.backend.baseline_calls[-1], (current, (), {}))
        for key in ("private_context_allocated", "graph_allocated", "stream_allocated", "buffers_allocated"):
            self.assertFalse(status[key])

    def test_restore_does_not_overwrite_another_patch_owner(self):
        handle = graph.install(self.detector, "graph")
        replacement = lambda im: "other owner"
        self.backend.forward = replacement
        with self.assertRaises(RuntimeError):
            handle.restore()
        self.assertIs(self.backend.forward, replacement)
        self.backend.forward = handle._replacement
        handle.restore()


if __name__ == "__main__":
    unittest.main()
