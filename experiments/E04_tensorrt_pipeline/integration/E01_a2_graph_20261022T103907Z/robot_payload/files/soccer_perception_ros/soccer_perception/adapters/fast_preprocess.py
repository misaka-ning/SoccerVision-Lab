"""Optional, serialized Ultralytics preprocessing with reusable buffers.

The uint8 OpenCV resize, letterbox geometry, channel order and normalization
match Ultralytics 8.3.159. Returned arrays/tensors belong to this object and are
overwritten by the next call. Use one instance per serialized predictor. H2D
copies deliberately remain blocking so the next frame cannot overwrite a host
buffer while CUDA is still reading it. No camera/ISP settings are changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class LetterboxGeometry:
    """Image-only geometry from the deployed Ultralytics LetterBox."""

    resized_wh: tuple[int, int]
    output_hw: tuple[int, int]
    top: int
    left: int


def letterbox_geometry(
    image_hw, imgsz, *, auto=False, stride=32, scale_fill=False,
    scaleup=True, center=True,
):
    target = (imgsz, imgsz) if isinstance(imgsz, int) else tuple(imgsz)
    height, width = image_hw
    ratio = min(target[0] / height, target[1] / width)
    if not scaleup:
        ratio = min(ratio, 1.0)
    resized = int(round(width * ratio)), int(round(height * ratio))
    dw, dh = target[1] - resized[0], target[0] - resized[1]
    if auto:
        dw, dh = np.mod(dw, stride), np.mod(dh, stride)
    elif scale_fill:
        dw, dh = 0.0, 0.0
        resized = target[1], target[0]
    if center:
        dw, dh = dw / 2, dh / 2
    top = int(round(dh - 0.1)) if center else 0
    bottom = int(round(dh + 0.1))
    left = int(round(dw - 0.1)) if center else 0
    right = int(round(dw + 0.1))
    return LetterboxGeometry(
        resized, (resized[1] + top + bottom, resized[0] + left + right), top, left
    )


class ReusablePreprocessor:
    """Reuse one letterbox canvas, a BCHW uint8 batch and device buffers."""

    def __init__(self):
        self._canvas = None
        self._canvas_geometry = None
        self._batch = None
        self._host_tensor = None
        self._device_u8 = None
        self._device_float = None
        self._tensor_key = None

    @staticmethod
    def supports(images):
        return isinstance(images, (list, tuple)) and len(images) > 0 and all(
            isinstance(image, np.ndarray)
            and image.dtype == np.uint8
            and image.ndim == 3
            and image.shape[2] == 3
            and image.shape[0] > 0
            and image.shape[1] > 0
            for image in images
        )

    def prepare_uint8(
        self, images: Sequence[np.ndarray], imgsz, *, auto=False, stride=32,
        scale_fill=False, scaleup=True, center=True,
    ):
        """Return borrowed contiguous RGB BCHW uint8 storage.

        Unsupported image types must use the original predictor path. The
        supplied stereo sequence is processed in its original order.
        """
        if not self.supports(images):
            raise ValueError("ReusablePreprocessor requires nonempty uint8 HWC BGR images")
        geometries = [letterbox_geometry(
            image.shape[:2], imgsz, auto=auto, stride=stride,
            scale_fill=scale_fill, scaleup=scaleup, center=center,
        ) for image in images]
        output_hw = geometries[0].output_hw
        if any(geometry.output_hw != output_hw for geometry in geometries):
            raise ValueError("all input arrays must have the same shape")
        batch_shape = (len(images), 3) + output_hw
        if self._batch is None or self._batch.shape != batch_shape:
            self._batch = np.empty(batch_shape, dtype=np.uint8)
            self._host_tensor = None
            self._tensor_key = None
        for index, (image, geometry) in enumerate(zip(images, geometries)):
            if self._canvas_geometry != geometry:
                self._canvas = np.full(geometry.output_hw + (3,), 114, dtype=np.uint8)
                self._canvas_geometry = geometry
            width, height = geometry.resized_wh
            destination = self._canvas[
                geometry.top:geometry.top + height,
                geometry.left:geometry.left + width,
            ]
            if image.shape[1::-1] == geometry.resized_wh:
                np.copyto(destination, image)
            else:
                cv2.resize(image, geometry.resized_wh, dst=destination, interpolation=cv2.INTER_LINEAR)
            np.copyto(self._batch[index], self._canvas[..., ::-1].transpose(2, 0, 1))
        return self._batch

    def preprocess(self, images, imgsz, *, device, fp16=False, auto=False, stride=32):
        """Match original uint8 H2D, floating conversion and in-place /255."""
        import torch

        batch = self.prepare_uint8(images, imgsz, auto=auto, stride=stride)
        device = torch.device(device)
        dtype = torch.float16 if fp16 else torch.float32
        key = (batch.shape, device, dtype)
        if self._host_tensor is None:
            self._host_tensor = torch.from_numpy(batch)
        if self._tensor_key != key:
            self._device_u8 = (
                self._host_tensor if device.type == "cpu"
                else torch.empty(batch.shape, dtype=torch.uint8, device=device)
            )
            self._device_float = torch.empty(batch.shape, dtype=dtype, device=device)
            self._tensor_key = key
        if device.type != "cpu":
            self._device_u8.copy_(self._host_tensor, non_blocking=False)
        self._device_float.copy_(self._device_u8)
        self._device_float.div_(255)
        return self._device_float

    def for_predictor(self, predictor, images):
        """Hook for Ultralytics 8.3.159; caller falls back for unsupported input.

        In a DetectionPredictor subclass, use this only for supported numpy
        images and call super().preprocess(im) for tensors/other input types.
        """
        same_shapes = len({image.shape for image in images}) == 1
        auto = (
            same_shapes and predictor.args.rect
            and (predictor.model.pt or (
                getattr(predictor.model, "dynamic", False) and not predictor.model.imx
            ))
        )
        return self.preprocess(
            images, predictor.imgsz, device=predictor.device,
            fp16=predictor.model.fp16, auto=auto, stride=predictor.model.stride,
        )
