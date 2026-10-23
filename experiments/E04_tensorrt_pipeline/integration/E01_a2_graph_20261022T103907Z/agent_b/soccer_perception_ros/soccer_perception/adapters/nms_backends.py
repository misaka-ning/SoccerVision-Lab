"""Optional, explicitly selected NMS experiments; no global monkeypatches.

The default reproduces the production pure Torch fallback. The NumPy candidate
keeps Torch's sort on the input device so equal-score ordering is unchanged.
It transfers sorted boxes once to CPU, then only kept positions back to the
input device. Benchmark the whole caller before promoting this candidate.
"""

from __future__ import annotations

import numpy as np


def torch_nms(boxes, scores, iou_threshold):
    """Production fallback copied without algorithm or truncation changes."""
    import torch

    if boxes.numel() == 0:
        return torch.empty((0,), dtype=torch.long, device=boxes.device)
    x1, y1, x2, y2 = boxes.unbind(dim=1)
    areas = (x2 - x1).clamp(min=0) * (y2 - y1).clamp(min=0)
    order = scores.argsort(descending=True)
    keep = []
    while order.numel() > 0:
        current = order[0]
        keep.append(current)
        if order.numel() == 1:
            break
        rest = order[1:]
        xx1 = torch.maximum(x1[current], x1[rest])
        yy1 = torch.maximum(y1[current], y1[rest])
        xx2 = torch.minimum(x2[current], x2[rest])
        yy2 = torch.minimum(y2[current], y2[rest])
        inter = (xx2 - xx1).clamp(min=0) * (yy2 - yy1).clamp(min=0)
        union = areas[current] + areas[rest] - inter
        iou = torch.where(union > 0, inter / union, torch.zeros_like(inter))
        order = rest[iou <= iou_threshold]
    return torch.stack(keep) if keep else torch.empty((0,), dtype=torch.long, device=boxes.device)


def numpy_nms(boxes, scores, iou_threshold):
    """FP32 greedy candidate with the original device's tie ordering.

    Keeps IoU == threshold, clamps negative widths/heights, and treats union <= 0
    as IoU zero, matching ``torch_nms``. No early max_det is applied. The fixed
    D2H/H2D boundary is deliberate and included in benchmark wall time.
    """
    import torch

    if boxes.ndim != 2 or boxes.shape[1] != 4 or scores.ndim != 1 or len(boxes) != len(scores):
        raise ValueError("NMS requires boxes[N,4] and scores[N]")
    if boxes.dtype != torch.float32 or scores.dtype != torch.float32:
        raise TypeError("NumPy NMS candidate is validated only for FP32 Engine I/O")
    if boxes.device != scores.device:
        raise ValueError("boxes and scores must use the same device")
    if boxes.numel() == 0:
        return torch.empty((0,), dtype=torch.long, device=boxes.device)

    order = scores.argsort(descending=True)
    sorted_boxes = boxes[order].detach().cpu().numpy()
    x1, y1, x2, y2 = sorted_boxes.T
    areas = np.maximum(x2 - x1, 0) * np.maximum(y2 - y1, 0)
    remaining = np.arange(len(sorted_boxes), dtype=np.int64)
    keep = []
    threshold = np.float32(iou_threshold)
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        while remaining.size:
            current = remaining[0]
            keep.append(current)
            if remaining.size == 1:
                break
            rest = remaining[1:]
            xx1 = np.maximum(x1[current], x1[rest])
            yy1 = np.maximum(y1[current], y1[rest])
            xx2 = np.minimum(x2[current], x2[rest])
            yy2 = np.minimum(y2[current], y2[rest])
            inter = np.maximum(xx2 - xx1, 0) * np.maximum(yy2 - yy1, 0)
            union = areas[current] + areas[rest] - inter
            iou = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)
            remaining = rest[iou <= threshold]
    positions = torch.as_tensor(np.asarray(keep, dtype=np.int64), device=boxes.device)
    return order[positions]


def torchvision_nms(boxes, scores, iou_threshold):
    """Call the compiled op directly, bypassing production's fallback patch.

    This candidate intentionally fails if custom ops are unavailable. Valid
    positive-area boxes and tie-sensitive Golden comparison are prerequisites
    for adoption; torchvision does not promise cross-device tie equivalence.
    """
    import torch
    import torchvision  # noqa: F401; registers torchvision::nms

    return torch.ops.torchvision.nms(boxes, scores, iou_threshold)


def probe_torchvision_nms(device="cuda:0"):
    """Probe the actual requested device once during experiment setup."""
    import torch

    report = {"device": str(device), "available": False}
    try:
        import torchvision

        report["torchvision"] = torchvision.__version__
        boxes = torch.tensor([[0., 0., 2., 2.], [0., 0., 2., 2.]], device=device)
        scores = torch.tensor([0.9, 0.8], device=device)
        keep = torchvision_nms(boxes, scores, 0.5)
        if boxes.is_cuda:
            torch.cuda.synchronize(boxes.device)
        report["available"] = keep.cpu().tolist() == [0]
        if not report["available"]:
            report["error"] = "compiled NMS smoke test returned unexpected indices"
    except Exception as exc:
        report["error"] = "%s: %s" % (type(exc).__name__, exc)
    return report


def dispatch_nms(boxes, scores, iou_threshold, backend="torch"):
    """Return int64 kept indices on the input device, with no truncation."""
    if backend == "torch":
        return torch_nms(boxes, scores, iou_threshold)
    if backend == "numpy":
        return numpy_nms(boxes, scores, iou_threshold)
    if backend == "torchvision":
        return torchvision_nms(boxes, scores, iou_threshold)
    raise ValueError("Unknown NMS backend: %s" % backend)
