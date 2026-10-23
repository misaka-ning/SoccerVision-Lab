"""Opt-in E02 single-class postprocessing; the caller keeps the existing NMS.

This module only specializes raw BCN detection output with one class and no
masks. Unsupported prediction formats and predictor features use Ultralytics.
No model, preprocessing, thresholds, NMS implementation or ROS protocol changes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

from soccer_perception.types import BallDetection


@dataclass
class FastDetectionResult:
    """Small internal result used only when YOLO rendering/saving is disabled.

    ``speed`` is assigned by BasePredictor.stream_inference. The array owns its
    CPU storage and remains valid across subsequent calls.
    """

    rows: np.ndarray
    speed: dict = field(default_factory=dict)


def single_class_nms(
    prediction,
    *,
    conf_thres: float,
    iou_thres: float,
    nms: Callable,
    xywh2xyxy: Callable,
    classes: Sequence[int] | None = None,
    max_det: int = 300,
    max_nms: int = 30000,
    max_time_img: float = 0.05,
):
    """Specialize Ultralytics 8.3.159's BCN nc=1 path, retaining its NMS.

    Filtering is strict ``score > conf``; excess candidates use the original
    Torch argsort; NMS sees the same coordinates, scores and IoU; max_det is
    applied after NMS. The input is not mutated. top_k belongs to the downstream
    candidate protocol and must not be used to truncate NMS input.
    """
    import torch

    if not 0 <= conf_thres <= 1 or not 0 <= iou_thres <= 1:
        raise ValueError("confidence and IoU thresholds must be between 0 and 1")
    if prediction.ndim != 3 or prediction.shape[1] != 5 or prediction.shape[-1] == 6:
        raise ValueError("single_class_nms requires unambiguous [B, 5, N] raw detection output")
    if prediction.dtype != torch.float32:
        raise ValueError("E02 single_class_nms requires the frozen FP32 engine output")
    if max_det < 0 or max_nms < 0:
        raise ValueError("max_det and max_nms must not be negative")

    output = [prediction.new_zeros((0, 6)) for _ in range(prediction.shape[0])]
    if classes is not None and 0 not in classes:
        return output
    started = time.time()
    time_limit = 2.0 + max_time_img * prediction.shape[0]
    # One confidence mask replaces amax, max+argmax and repeated class masks.
    for index, raw in enumerate(prediction.transpose(1, 2)):
        selected = raw[raw[:, 4] > conf_thres]
        if not selected.shape[0]:
            continue
        rows = selected.new_empty((selected.shape[0], 6))
        rows[:, :4] = xywh2xyxy(selected[:, :4])
        rows[:, 4] = selected[:, 4]
        rows[:, 5] = 0.0
        if rows.shape[0] > max_nms:
            rows = rows[rows[:, 4].argsort(descending=True)[:max_nms]]
        # Class zero means the original class offset is exactly zero. Leave
        # the callback untouched, including its ordering and tie behavior.
        keep = nms(rows[:, :4], rows[:, 4], iou_thres)[:max_det]
        output[index] = rows[keep]
        if time.time() - started > time_limit:
            import warnings

            warnings.warn("E02 NMS time limit %.3fs exceeded" % time_limit, RuntimeWarning)
            break
    return output


def batch_rows_to_numpy(rows) -> list[np.ndarray]:
    """Transfer all eyes' final Nx6 rows together with one .cpu() call.

    The concatenated CPU tensor owns its storage. No pinned reusable host buffer
    is exposed to callers, so retaining an older result cannot observe new data.
    Empty batches avoid a CUDA transfer entirely.
    """
    import torch

    lengths = [row.shape[0] for row in rows]
    if not any(lengths):
        return [np.empty((0, 6), dtype=np.float32) for _ in rows]
    merged = torch.cat(rows, dim=0).detach().cpu().numpy()
    boundaries = np.cumsum([0] + lengths)
    return [merged[boundaries[i]:boundaries[i + 1]] for i in range(len(lengths))]


def rows_to_candidates(
    rows: np.ndarray,
    *,
    names: dict[int, str],
    top_k: int | None = None,
) -> list[BallDetection]:
    """Preserve YoloBallDetector's detection protocol and stable score ordering.

    Sorting and top_k happen before constructing Python objects, with the same
    stable ordering as list.sort. None, zero and negative top_k keep all rows.
    """
    if not len(rows):
        return []
    order = np.argsort(-rows[:, 4], kind="stable")
    if top_k is not None and top_k > 0:
        order = order[:top_k]
    candidates = []
    for row in rows[order]:
        x1, y1, x2, y2, conf, cls_id = [float(value) for value in row]
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        class_id = int(cls_id)
        candidates.append(
            BallDetection(
                center=np.array([(x1 + x2) * 0.5, (y1 + y2) * 0.5], dtype=np.float64),
                radius_px=float(0.5 * max(width, height)),
                score=float(conf),
                bbox=(int(round(x1)), int(round(y1)), int(round(width)), int(round(height))),
                source="yolo",
                class_id=class_id,
                class_name=str(names.get(class_id, "")),
            )
        )
    return candidates


def make_fast_predictor_class(nms: Callable | None = None):
    """Return a DetectionPredictor subclass for explicit E02 opt-in wiring.

    It uses the currently installed original NMS unless a candidate callback is
    deliberately supplied by the integration harness. The adapter must consume
    FastDetectionResult with rows_to_candidates; ordinary Results keep their
    existing converter. No global Ultralytics functions are replaced.
    """
    import torch
    from ultralytics.models.yolo.detect.predict import DetectionPredictor
    from ultralytics.utils import ops

    class FastSingleClassPredictor(DetectionPredictor):
        def postprocess(self, preds, img, orig_imgs, **kwargs):
            raw = preds[0] if isinstance(preds, (tuple, list)) else preds
            names = getattr(self.model, "names", {})
            supported = (
                isinstance(raw, torch.Tensor)
                and raw.ndim == 3
                and raw.shape[1] == 5
                and raw.shape[-1] != 6
                and raw.dtype == torch.float32
                and self.args.task == "detect"
                and len(names) == 1
                and (isinstance(names, (list, tuple)) or 0 in names)
                and not getattr(self.model, "end2end", False)
                and isinstance(orig_imgs, list)
                and len(orig_imgs) == raw.shape[0]
                and getattr(self, "_feats", None) is None
                and not any(getattr(self.args, flag, False) for flag in (
                    "verbose", "save", "save_txt", "save_crop", "show", "visualize", "embed"
                ))
                and not kwargs
            )
            if not supported:
                return super().postprocess(preds, img, orig_imgs, **kwargs)
            callback = nms
            if callback is None:
                import torchvision

                callback = torchvision.ops.nms
            rows = single_class_nms(
                raw,
                conf_thres=self.args.conf,
                iou_thres=self.args.iou,
                classes=self.args.classes,
                max_det=self.args.max_det,
                nms=callback,
                xywh2xyxy=ops.xywh2xyxy,
            )
            for row, orig_img in zip(rows, orig_imgs):
                row[:, :4] = ops.scale_boxes(img.shape[2:], row[:, :4], orig_img.shape)
            return [FastDetectionResult(row) for row in batch_rows_to_numpy(rows)]

    return FastSingleClassPredictor
