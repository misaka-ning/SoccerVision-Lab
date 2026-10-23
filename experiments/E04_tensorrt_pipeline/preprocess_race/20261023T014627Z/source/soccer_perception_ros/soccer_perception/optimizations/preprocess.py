"""Opt-in E04 preprocessing probes and host packing buffer reuse.

The production predictor owns resize/letterbox.  This module deliberately calls
that unchanged pre_transform and changes only packing of its uint8 outputs.
No CUDA streams, GPU output buffers, frames or timestamps are retained here.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

import numpy as np
import torch


_VARIANTS = ("c0", "c1", "c2")
_SHAPE = (2, 3, 640, 640)
_MARKER = "_e04_preprocess_handle"


class PreprocessHandle:
    """One predictor instance; c1 measures method walls, c2 reuses host storage."""

    def __init__(self, detector: Any, variant: str) -> None:
        if variant not in _VARIANTS:
            raise ValueError("preprocess variant must be c0, c1 or c2")
        predictor = getattr(getattr(detector, "model", None), "predictor", None)
        if predictor is None or not callable(getattr(predictor, "preprocess", None)):
            raise ValueError("initialize the detector predictor before install")
        if getattr(predictor, _MARKER, None) is not None:
            raise ValueError("restore the existing E04 preprocessing handle first")
        self._predictor = predictor
        self._requested = variant
        self._effective = "c0"
        self._original = predictor.preprocess
        self._had_instance_method = "preprocess" in vars(predictor)
        self._instance_method = vars(predictor).get("preprocess")
        self._lock = threading.RLock()
        self._restored = False
        self._calls = 0
        self._successes = 0
        self._fallbacks = 0
        self._last_error = None  # type: Optional[str]
        self._input_shapes = None
        self._host = None  # type: Optional[np.ndarray]
        self._host_tensor = None
        self._host_allocations = 0
        self._timings = {}  # type: Dict[str, Dict[str, Any]]
        self._wrapper = self._preprocess
        if variant != "c0":
            predictor.preprocess = self._wrapper
            setattr(predictor, _MARKER, self)

    def _timed(self, name: str, function: Any) -> Any:
        start = time.perf_counter_ns()
        try:
            return function()
        finally:
            elapsed = (time.perf_counter_ns() - start) / 1e6
            item = self._timings.setdefault(
                name, {"count": 0, "total_ms": 0.0, "last_ms": 0.0, "max_ms": 0.0}
            )
            item["count"] += 1
            item["total_ms"] += elapsed
            item["last_ms"] = elapsed
            item["max_ms"] = max(item["max_ms"], elapsed)

    def _profile(self, images: Any) -> torch.Tensor:
        # Keep the audited predictor's operation order, dtype and normalization.
        not_tensor = not isinstance(images, torch.Tensor)
        if not_tensor:
            transformed = self._timed("pre_transform", lambda: self._predictor.pre_transform(images))
            value = self._timed("stack", lambda: np.stack(transformed))

            def layout() -> np.ndarray:
                rgb = value[..., ::-1] if value.shape[-1] == 3 else value
                return rgb.transpose((0, 3, 1, 2))

            value = self._timed("color_layout_views", layout)
            value = self._timed("contiguous_pack", lambda: np.ascontiguousarray(value))
            value = self._timed("from_numpy", lambda: torch.from_numpy(value))
        else:
            value = images
        value = self._timed("to_device", lambda: value.to(self._predictor.device))
        value = self._timed("dtype", lambda: value.half() if self._predictor.model.fp16 else value.float())
        if not_tensor:
            value = self._timed("normalize", lambda: value.div_(255))
        return value

    def _unsupported(self, images: Any) -> Optional[str]:
        model = self._predictor.model
        if getattr(model, "fp16", True):
            return "c2 requires the frozen FP32 input backend"
        if getattr(model, "dynamic", False):
            return "c2 supports the frozen static shape backend only"
        size = getattr(self._predictor, "imgsz", None)
        if not isinstance(size, (list, tuple)) or tuple(size) != (640, 640):
            return "predictor image size differs from frozen 640x640"
        if not isinstance(images, (list, tuple)) or len(images) != 2:
            return "c2 requires a left/right list or tuple of two images"
        if any(not isinstance(x, np.ndarray) or x.dtype != np.uint8 or x.ndim != 3 or x.shape[2] != 3
               for x in images):
            return "c2 requires uint8 HWC BGR images with three channels"
        shapes = tuple(tuple(x.shape) for x in images)
        if shapes[0] != shapes[1]:
            return "left/right input shapes differ"
        if self._input_shapes is not None and shapes != self._input_shapes:
            return "input shape changed after the first successful c2 batch"
        return None

    def _reuse(self, images: Any) -> torch.Tensor:
        transformed = self._predictor.pre_transform(images)
        if len(transformed) != 2 or any(
            not isinstance(x, np.ndarray) or x.dtype != np.uint8 or x.shape != (640, 640, 3)
            for x in transformed
        ):
            raise ValueError("pre_transform did not return two uint8 640x640 BGR images")
        if self._host is None:
            host = np.empty(_SHAPE, dtype=np.uint8)
            host_tensor = torch.from_numpy(host)
            self._host = host
            self._host_tensor = host_tensor
            self._host_allocations += 1
        for eye, image in enumerate(transformed):
            # Copy directly into final BCHW storage. Negative source strides are
            # handled by numpy; caller arrays and letterbox pixels are untouched.
            np.copyto(self._host[eye], image.transpose(2, 0, 1)[::-1], casting="no")
        # The default blocking transfer must finish reading the reusable host
        # storage before this method can return. No non_blocking copy or pinned
        # host storage is introduced. float() allocates a separate FP32 result,
        # even for CPU validation, so the next pack cannot overwrite old output.
        value = self._host_tensor.to(self._predictor.device)
        value = value.float()
        value /= 255
        self._input_shapes = tuple(tuple(x.shape) for x in images)
        return value

    def _fallback(self, images: Any, reason: str) -> torch.Tensor:
        self._fallbacks += 1
        self._effective = "c0"
        self._last_error = reason[:500]
        return self._original(images)

    def _preprocess(self, im: Any) -> torch.Tensor:
        images = im  # Preserve the audited preprocess(im=...) keyword contract.
        with self._lock:
            if self._restored:
                return self._original(images)
            self._calls += 1
            if self._requested == "c1":
                try:
                    result = self._profile(images)
                except Exception as exc:
                    return self._fallback(images, "c1: %s: %s" % (type(exc).__name__, exc))
            else:
                reason = self._unsupported(images)
                if reason is not None:
                    return self._fallback(images, reason)
                try:
                    result = self._reuse(images)
                except Exception as exc:
                    return self._fallback(images, "c2: %s: %s" % (type(exc).__name__, exc))
            self._successes += 1
            self._effective = self._requested
            return result

    def describe(self) -> Dict[str, Any]:
        with self._lock:
            timings = {}
            for key, item in self._timings.items():
                timings[key] = dict(item, mean_ms=item["total_ms"] / item["count"])
            return {
                "requested": self._requested,
                "effective": "c0" if self._restored else self._effective,
                "restored": self._restored,
                "calls": self._calls,
                "success_count": self._successes,
                "fallback_count": self._fallbacks,
                "last_error": self._last_error,
                "output_shape": list(_SHAPE),
                "output_dtype": "float32",
                "device": str(self._predictor.device),
                "input_shapes": self._input_shapes,
                "host_buffer_allocations": self._host_allocations,
                "host_tensor_view_allocations": self._host_allocations,
                "host_buffer_bytes": 0 if self._host is None else self._host.nbytes,
                "host_buffer_owner": "handle; uint8 BCHW, no caller-array aliases",
                "gpu_output_buffer_reused": False,
                "output_owner": "per-call FP32 tensor; caller may retain earlier batches",
                "transfer": "original blocking Tensor.to(device), non_blocking=False",
                "timing_scope": "c1 method wall milliseconds; no added CUDA synchronization; not kernel times",
                "timings": timings,
                "cuda_validation": "external coordinator correctness/performance check required",
            }

    def restore(self) -> None:
        with self._lock:
            if self._restored:
                return
            if self._requested != "c0":
                # Root owns hook installation order; report accidental hook
                # replacement while still providing unconditional baseline restore.
                if self._predictor.preprocess is not self._wrapper:
                    self._last_error = "preprocess hook changed before restore; restored saved original"
                if self._had_instance_method:
                    self._predictor.preprocess = self._instance_method
                else:
                    self._predictor.__dict__.pop("preprocess", None)
                if getattr(self._predictor, _MARKER, None) is self:
                    delattr(self._predictor, _MARKER)
            self._host_tensor = None
            self._host = None
            self._restored = True


def install(detector: Any, variant: str = "c0") -> PreprocessHandle:
    """Install after predictor initialization, before benchmark warmup.

    c0 leaves the original method untouched. c1 is a diagnostic probe only.
    c2 is an unapproved candidate until robot correctness and A/B validation.
    """
    return PreprocessHandle(detector, variant)
