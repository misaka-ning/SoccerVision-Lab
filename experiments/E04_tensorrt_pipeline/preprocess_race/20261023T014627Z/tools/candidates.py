"""Two isolated preprocessing candidates for the frozen E01 stereo predictor.

Install after detector.load(), before the first real-image warmup. This is a
benchmark payload, not a production default. Only serialized predictor calls
are supported (the deployed Ultralytics predictor already owns that lock).
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional

import cv2
import numpy as np
import torch

from soccer_perception.adapters.fast_preprocess import ReusablePreprocessor, letterbox_geometry


_MARKER = "_e04_preprocess_race_handle"
_OUTPUT_SHAPE = (2, 3, 640, 640)


class CandidateHandle:
    """Save and unconditionally restore the selected original instance hook."""

    def __init__(self, predictor: Any, variant: str) -> None:
        if variant not in ("canvas", "reuse"):
            raise ValueError("variant must be canvas or reuse")
        if not callable(getattr(predictor, "preprocess", None)) or not callable(
            getattr(predictor, "pre_transform", None)
        ):
            raise ValueError("initialize predictor before installing preprocessing candidate")
        if getattr(predictor, _MARKER, None) is not None:
            raise ValueError("restore the installed preprocessing race handle first")
        self._predictor = predictor
        self._variant = variant
        self._method_name = "pre_transform" if variant == "canvas" else "preprocess"
        self._original = getattr(predictor, self._method_name)
        self._had_instance_method = self._method_name in vars(predictor)
        self._instance_method = vars(predictor).get(self._method_name)
        self._lock = threading.RLock()
        self._restored = False
        self._calls = self._successes = self._fallbacks = self._restore_count = 0
        self._last_error = None  # type: Optional[str]
        self._effective = "baseline"
        self._input_shapes = None
        self._canvases = None
        self._geometry = None
        self._canvas_allocations = 0
        self._host_allocations = self._host_view_allocations = self._float_allocations = 0
        self._packer = ReusablePreprocessor() if variant == "reuse" else None
        self._wrapper = self._apply
        setattr(predictor, self._method_name, self._wrapper)
        setattr(predictor, _MARKER, self)

    def _unsupported(self, images: Any) -> Optional[str]:
        model = self._predictor.model
        if getattr(model, "fp16", True):
            return "requires frozen FP32 input backend"
        if getattr(model, "pt", True) or getattr(model, "dynamic", False):
            return "requires frozen static TensorRT backend"
        size = getattr(self._predictor, "imgsz", None)
        if not isinstance(size, (list, tuple)) or tuple(size) != (640, 640):
            return "requires frozen predictor.imgsz [640,640]"
        if not isinstance(images, (list, tuple)) or len(images) != 2:
            return "requires left/right sequence of two uint8 BGR images"
        if not ReusablePreprocessor.supports(images):
            return "requires positive uint8 HWC images with three channels"
        shapes = tuple(tuple(image.shape) for image in images)
        if shapes[0] != shapes[1]:
            return "left/right image shapes differ"
        if self._input_shapes is not None and shapes != self._input_shapes:
            return "image shape changed after first successful real-image batch"
        return None

    def _canvas(self, images: Any) -> Any:
        if self._canvases is None:
            geometry = letterbox_geometry(images[0].shape[:2], (640, 640), auto=False)
            if geometry.output_hw != (640, 640):
                raise ValueError("unexpected letterbox output shape")
            self._canvases = [np.full((640, 640, 3), 114, np.uint8) for _ in range(2)]
            self._geometry = geometry
            self._canvas_allocations += 2
        geometry = self._geometry
        width, height = geometry.resized_wh
        for image, canvas in zip(images, self._canvases):
            destination = canvas[
                geometry.top:geometry.top + height,
                geometry.left:geometry.left + width,
            ]
            if image.shape[1::-1] == geometry.resized_wh:
                np.copyto(destination, image)
            else:
                cv2.resize(image, geometry.resized_wh, dst=destination, interpolation=cv2.INTER_LINEAR)
        # Both eyes must have distinct storage: the original preprocess stacks
        # these synchronously immediately after this method returns. Direct
        # callers retaining pre_transform outputs must copy the borrowed arrays.
        return self._canvases

    def _reuse(self, images: Any) -> torch.Tensor:
        packer = self._packer
        old_canvas, old_batch = packer._canvas, packer._batch
        batch = packer.prepare_uint8(images, (640, 640), auto=False)
        self._canvas_allocations += int(packer._canvas is not old_canvas)
        self._host_allocations += int(packer._batch is not old_batch)
        if packer._host_tensor is None:
            packer._host_tensor = torch.from_numpy(batch)
            self._host_view_allocations += 1
        # Deliberately avoid ReusablePreprocessor.preprocess(): its borrowed
        # _device_float can be overwritten by a later call. Here every FP32
        # output and CUDA uint8 staging tensor is independent. Blocking to()
        # completes host reads before the next call can reuse the CPU buffers.
        value = packer._host_tensor.to(self._predictor.device, non_blocking=False)
        value = value.float()
        self._float_allocations += 1
        value.div_(255)
        return value

    def _fallback(self, images: Any, reason: str) -> Any:
        self._fallbacks += 1
        self._effective = "baseline"
        self._last_error = reason[:500]
        return self._original(images)

    def _apply(self, im: Any) -> Any:
        with self._lock:
            if self._restored:
                return self._original(im)
            self._calls += 1
            reason = self._unsupported(im)
            if reason is not None:
                return self._fallback(im, reason)
            try:
                result = self._canvas(im) if self._variant == "canvas" else self._reuse(im)
            except Exception as exc:
                return self._fallback(im, "%s: %s" % (type(exc).__name__, exc))
            self._input_shapes = tuple(tuple(image.shape) for image in im)
            self._successes += 1
            self._effective = self._variant
            return result

    def describe(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "requested": self._variant,
                "effective": "baseline" if self._restored else self._effective,
                "restored": self._restored,
                "calls": self._calls,
                "success_count": self._successes,
                "fallback_count": self._fallbacks,
                "restore_count": self._restore_count,
                "last_error": self._last_error,
                "hook": self._method_name,
                "input_shapes": self._input_shapes,
                "output_shape": list(_OUTPUT_SHAPE),
                "output_dtype": "float32",
                "device": str(self._predictor.device),
                "canvas_allocations": self._canvas_allocations,
                "host_buffer_allocations": self._host_allocations,
                "host_tensor_view_allocations": self._host_view_allocations,
                "fp32_output_allocations": self._float_allocations if self._variant == "reuse" else None,
                "gpu_output_buffer_reused": False,
                "gpu_uint8_buffer_reused": False,
                "host_buffer_owner": "handle; no alias of caller input images",
                "pre_transform_output_owner": (
                    "two borrowed per-eye HWC canvases; original preprocess immediately np.stack copies"
                    if self._variant == "canvas" else "internal single canvas copied into BCHW host batch"
                ),
                "output_owner": "per-call independent FP32 tensor; caller may retain earlier output",
                "transfer": "original blocking Tensor.to(device), non_blocking=False",
                "concurrency": "one serialized predictor; no asynchronous overlap or extra streams",
                "cuda_validation": "not performed by this CPU-only candidate developer",
            }

    def restore(self) -> None:
        with self._lock:
            if self._restored:
                return
            if getattr(self._predictor, self._method_name) is not self._wrapper:
                self._last_error = "hook changed before restore; restored saved original"
            if self._had_instance_method:
                setattr(self._predictor, self._method_name, self._instance_method)
            else:
                vars(self._predictor).pop(self._method_name, None)
            if getattr(self._predictor, _MARKER, None) is self:
                delattr(self._predictor, _MARKER)
            self._canvases = self._geometry = self._packer = None
            self._restored = True
            self._restore_count += 1


def install(predictor: Any, variant: str) -> CandidateHandle:
    """Install canvas/reuse after load(), before real-image correctness/warmup."""
    return CandidateHandle(predictor, variant)
