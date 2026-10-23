"""Opt-in E04 TensorRT 8.x CUDA Graph execution; no engine or global patch.

Install after the Ultralytics predictor/backend has been initialized. The graph
owns a separate execution context and buffers; AutoBackend's context, bindings,
and baseline forward remain untouched. CUDA validation belongs to the robot
benchmark, not the CPU unit tests in this change.
"""

import threading
import types


INPUT_SHAPE = (2, 3, 640, 640)
OUTPUT_SHAPE = (2, 5, 8400)
_MISSING = object()


class GraphExecutionError(RuntimeError):
    """A CUDA error prevented safe fallback; the caller must reject the frame."""


class _CudaGraphRunner:
    """Private, single-stream static TRT execution. Constructor is lazy."""

    def __init__(self, backend):
        import torch

        self.torch = torch
        self.backend = backend
        self.context = None
        self.stream = None
        self.graph = None
        self.input = None
        self.output = None
        self.addresses = None
        self.device = backend.bindings["images"].data.device
        self.capture_count = 0
        self.replay_count = 0
        self.input_update_count = 0
        self.warmup_enqueue_count = 0
        self.output_clone_count = 0
        self._validate_backend()

    def _validate_backend(self):
        torch = self.torch
        backend = self.backend
        engine = backend.model
        if not getattr(backend, "engine", False):
            raise ValueError("Graph requires a TensorRT backend")
        if getattr(backend, "dynamic", True) or getattr(backend, "is_trt10", True):
            raise ValueError("Graph supports this experiment's static TensorRT 8.x engine only")
        if getattr(backend, "fp16", True) or getattr(backend, "nhwc", True):
            raise ValueError("Graph requires FP32 BCHW external I/O")
        if not torch.cuda.is_available() or self.device.type != "cuda":
            raise ValueError("Graph requires CUDA")
        if engine.has_implicit_batch_dimension or engine.num_bindings != 2:
            raise ValueError("Graph requires explicit batch and exactly two bindings")
        self.names = [engine.get_binding_name(i) for i in range(engine.num_bindings)]
        self.output_names = list(backend.output_names)
        if self.names.count("images") != 1 or len(self.output_names) != 1:
            raise ValueError("Graph requires one 'images' input and one output")
        for index, name in enumerate(self.names):
            binding = backend.bindings[name]
            expected = INPUT_SHAPE if name == "images" else OUTPUT_SHAPE
            if bool(engine.binding_is_input(index)) != (name == "images"):
                raise ValueError("Unexpected TensorRT input/output binding layout")
            if tuple(engine.get_binding_shape(index)) != expected or tuple(binding.shape) != expected:
                raise ValueError("Unexpected TensorRT binding shape: " + name)
            if binding.data.dtype != torch.float32 or binding.data.device != self.device:
                raise ValueError("Unexpected TensorRT binding dtype/device: " + name)
            if hasattr(engine, "is_shape_binding") and engine.is_shape_binding(index):
                raise ValueError("Shape bindings are unsupported")
        if self.output_names[0] not in self.names or self.output_names[0] == "images":
            raise ValueError("Unexpected output binding name")

    def validate_input(self, im):
        if tuple(im.shape) != INPUT_SHAPE:
            raise ValueError("Graph input shape must be [2,3,640,640]")
        if im.dtype != self.torch.float32 or im.device != self.device or not im.is_contiguous():
            raise ValueError("Graph input must be contiguous FP32 on the engine CUDA device")

    def _enqueue(self):
        success = self.context.execute_async_v2(
            bindings=self.addresses, stream_handle=self.stream.cuda_stream
        )
        if success is not True:
            raise RuntimeError("TensorRT execute_async_v2 returned false")

    def _initialize(self, im, caller):
        torch = self.torch
        # Allocation and all context initialization happen before capture. The
        # owning handle retains this object even when initialization fails.
        self.stream = torch.cuda.Stream(device=self.device)
        with torch.cuda.stream(self.stream):
            self.input = torch.empty(INPUT_SHAPE, dtype=torch.float32, device=self.device)
            self.output = torch.empty(OUTPUT_SHAPE, dtype=torch.float32, device=self.device)
            self.context = self.backend.model.create_execution_context()
            if self.context is None:
                raise RuntimeError("Failed to create independent TensorRT execution context")
            self.addresses = [
                int((self.input if name == "images" else self.output).data_ptr()) for name in self.names
            ]
            self.stream.wait_stream(caller)
            self.input.copy_(im, non_blocking=True)
            im.record_stream(self.stream)
            for _ in range(3):
                self._enqueue()
                self.warmup_enqueue_count += 1
        self.stream.synchronize()
        self.graph = torch.cuda.CUDAGraph()
        # TensorRT's first enqueue is deliberately outside capture. Capture has
        # no tensor allocation, copies, host synchronization or NMS.
        with torch.cuda.graph(self.graph, stream=self.stream):
            self._enqueue()
        self.capture_count += 1

    def run(self, im):
        self.validate_input(im)
        torch = self.torch
        with torch.cuda.device(self.device):
            caller = torch.cuda.current_stream(self.device)
            if self.graph is None:
                self._initialize(im, caller)
            with torch.cuda.stream(self.stream):
                # The caller's preceding preprocessing AND prior use of any
                # returned output must complete before updating stable storage.
                self.stream.wait_stream(caller)
                self.input.copy_(im, non_blocking=True)
                im.record_stream(self.stream)
                self.input_update_count += 1
                self.graph.replay()
                self.replay_count += 1
                # Each call owns its returned storage. External NMS can mutate
                # it without touching captured buffers or a later call's result.
                result = self.output.clone()
                self.output_clone_count += 1
            caller.wait_stream(self.stream)
            result.record_stream(caller)
            return result

    def synchronize(self):
        if self.stream is not None:
            self.stream.synchronize()

    def close(self):
        # Never release context/buffers while their work is still outstanding.
        # If synchronize fails, retain ownership and propagate the CUDA error.
        self.synchronize()
        self.graph = None
        self.context = None
        self.input = None
        self.output = None
        self.addresses = None
        self.stream = None
        self.backend = None

    def describe(self):
        return {
            "capture_count": self.capture_count,
            "replay_count": self.replay_count,
            "input_update_count": self.input_update_count,
            "warmup_enqueue_count": self.warmup_enqueue_count,
            "output_clone_count": self.output_clone_count,
            "input_shape": list(INPUT_SHAPE),
            "output_shape": list(OUTPUT_SHAPE),
            "input_dtype": "float32",
            "output_dtype": "float32",
            "output_names": list(self.output_names),
            "device": str(self.device),
            "private_context_allocated": self.context is not None,
            "graph_allocated": self.graph is not None,
            "stream_allocated": self.stream is not None,
            "buffers_allocated": self.input is not None or self.output is not None,
        }


class GraphHandle:
    def __init__(self, backend, variant):
        self.backend = backend
        self.requested = variant
        self.effective = "b0" if variant == "b0" else "pending_capture"
        self.fallback_count = 0
        self.last_error = None
        self.disabled_reason = None
        self.cleanup_error = None
        self.calls = 0
        self._runner = None
        self._retired_stats = {}
        self._original_forward = backend.forward
        self._old_instance_forward = backend.__dict__.get("forward", _MISSING)
        self._lock = threading.RLock()
        self._restored = False
        if variant == "graph":
            def forward(_backend, im, *args, **kwargs):
                return self._forward(im, args, kwargs)

            self._replacement = types.MethodType(forward, backend)
            backend.forward = self._replacement
            backend._e04_graph_handle = self

    def _disable(self, error):
        self.last_error = "{}: {}".format(type(error).__name__, error)
        self.disabled_reason = self.last_error
        self.effective = "b0"
        if self._runner is not None:
            self._retired_stats = self._runner.describe()
            try:
                self._runner.close()
            except Exception as cleanup_error:
                self.cleanup_error = "{}: {}".format(type(cleanup_error).__name__, cleanup_error)
                raise GraphExecutionError(
                    "Cannot safely fall back after Graph failure: " + self.cleanup_error
                ) from cleanup_error
            self._retired_stats = self._runner.describe()
            self._runner = None

    def _forward(self, im, args, kwargs):
        with self._lock:
            self.calls += 1
            if self._restored or self.disabled_reason is not None:
                self.fallback_count += 1
                return self._original_forward(im, *args, **kwargs)
            try:
                # Original TRT forward ignores augmentation/embedding options,
                # but delegate unusual calls rather than guessing semantics.
                if args or any(value not in (None, False) for value in kwargs.values()):
                    raise ValueError("Graph requires the ordinary backend forward signature")
                if self._runner is None:
                    self._runner = _CudaGraphRunner(self.backend)
                result = self._runner.run(im)
                self.effective = "graph"
                return result
            except Exception as error:
                self._disable(error)
                self.fallback_count += 1
                return self._original_forward(im, *args, **kwargs)

    def synchronize(self):
        """Optional test boundary; detect asynchronous CUDA failures explicitly."""
        with self._lock:
            if self._runner is not None:
                try:
                    self._runner.synchronize()
                except Exception as error:
                    self._disable(error)
                    # No current input is available to re-execute safely here.
                    raise GraphExecutionError("Asynchronous Graph failure: " + self.last_error) from error

    def describe(self):
        with self._lock:
            status = {
                "requested": self.requested,
                "effective": "restored" if self._restored else self.effective,
                "fallback_count": self.fallback_count,
                "last_error": self.last_error,
                "disabled_reason": self.disabled_reason,
                "cleanup_error": self.cleanup_error,
                "calls": self.calls,
                "capture_count": 0,
                "replay_count": 0,
                "input_update_count": 0,
                "warmup_enqueue_count": 0,
                "output_clone_count": 0,
                "input_shape": list(INPUT_SHAPE),
                "output_shape": list(OUTPUT_SHAPE),
                "input_dtype": "float32",
                "output_dtype": "float32",
                "output_names": list(getattr(self.backend, "output_names", [])),
                "private_context_allocated": False,
                "graph_allocated": False,
                "stream_allocated": False,
                "buffers_allocated": False,
                "counter_scope": "successfully enqueued; synchronize/output read validates CUDA completion",
                "input_update_policy": "current caller stream -> owned stream -> graph -> owned output clone -> caller",
            }
            status.update(self._runner.describe() if self._runner is not None else self._retired_stats)
            return status

    def restore(self):
        with self._lock:
            if self._restored and self._runner is None:
                return
            if not self._restored and self.requested == "graph":
                if self.backend.__dict__.get("forward") is self._replacement:
                    if self._old_instance_forward is _MISSING:
                        delattr(self.backend, "forward")
                    else:
                        self.backend.forward = self._old_instance_forward
                else:
                    raise RuntimeError("backend.forward was replaced by another owner; refusing to clobber it")
                if getattr(self.backend, "_e04_graph_handle", None) is self:
                    delattr(self.backend, "_e04_graph_handle")
            self._restored = True
            if self._runner is not None:
                try:
                    self._runner.close()
                    self._retired_stats = self._runner.describe()
                    self._runner = None
                except Exception as error:
                    self.cleanup_error = "{}: {}".format(type(error).__name__, error)
                    raise GraphExecutionError("Original forward restored, but Graph cleanup failed") from error


def install(detector, variant="b0"):
    """Install on this initialized detector instance only; b0 leaves it intact.

    ``graph`` becomes effective only after a successful captured execution. The
    caller must reject a Graph performance trial if effective != graph or any
    fallback occurred; a baseline result is never proof that capture succeeded.
    """
    normalized = str(variant).lower()
    if normalized not in ("b0", "graph"):
        raise ValueError("Unknown Graph variant: " + str(variant))
    predictor = getattr(getattr(detector, "model", None), "predictor", None)
    backend = getattr(predictor, "model", None)
    if backend is None or not callable(getattr(backend, "forward", None)):
        raise ValueError("Initialize detector.model.predictor.model before installing Graph")
    if getattr(backend, "_e04_graph_handle", None) is not None:
        raise RuntimeError("An E04 Graph handle is already installed on this backend")
    return GraphHandle(backend, normalized)
