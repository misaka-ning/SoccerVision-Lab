"""Opt-in E04 result conversion; the original predictor and NMS stay in use.

``a1`` changes only CPU candidate construction. ``a2`` changes only the
transfer of final (already suppressed and scaled) Boxes tensors. Both can be
measured independently; ``a1+a2`` is available for an explicit combined test.
No optimization is installed by importing this module.
"""

from __future__ import annotations

import copy
import time
from types import MethodType

import numpy as np

from soccer_perception.types import BallDetection


_ABSENT = object()


class PostprocessHandle:
    def __init__(self, detector, variant):
        normalized = str(variant).strip().lower()
        if normalized not in {"a0", "a1", "a2", "a3", "a1+a2"}:
            raise ValueError("postprocess variant must be a0/a1/a2/a3/a1+a2")
        if getattr(detector, "_e04_postprocess_handle", None) is not None:
            raise RuntimeError("restore the active postprocess handle before installing another")
        self.detector = detector
        self.requested = normalized
        self.effective = normalized
        self.restored = False
        self.fallback_count = 0
        self.last_error = None
        self.calls = 0
        self.converted_results = 0
        self.packed_batches = 0
        self.packed_rows = 0
        self.d2h_calls = 0
        self.d2h_bytes = 0
        self.last_pack_wall_ms = 0.0
        self.pack_wall_ms_total = 0.0
        self._patches = []
        self._original_convert = detector._result_to_candidates
        if normalized == "a3":
            self.effective = "a0"
            self.last_error = (
                "A3 unavailable: robot torchvision _C.so has a Torch ABI symbol "
                "failure; no compatible isolated NMS has been validated. Original NMS retained."
            )
            self.fallback_count = 1
        if normalized in {"a1", "a1+a2"}:
            self._patch(detector, "_result_to_candidates", MethodType(self._convert, detector))
        if normalized in {"a2", "a1+a2"}:
            model = getattr(detector, "model", None)
            if model is None or not callable(getattr(model, "predict", None)):
                self.restore()
                raise RuntimeError("initialize the detector model before installing a2")
            original_predict = model.predict

            def predict(_model, *args, **kwargs):
                # Never retry inference: fallback uses these very same results.
                results = original_predict(*args, **kwargs)
                self.calls += 1
                start = time.perf_counter()
                try:
                    return self._pack_final_results(results)
                except Exception as exc:
                    self._fallback(exc)
                    return results
                finally:
                    self.last_pack_wall_ms = (time.perf_counter() - start) * 1000.0
                    self.pack_wall_ms_total += self.last_pack_wall_ms

            self._patch(model, "predict", MethodType(predict, model))
        detector._e04_postprocess_handle = self

    def _patch(self, obj, name, value):
        old = vars(obj).get(name, _ABSENT)
        self._patches.append((obj, name, old, value))
        setattr(obj, name, value)

    def _fallback(self, error):
        self.fallback_count += 1
        self.last_error = "{}: {}".format(type(error).__name__, error)

    def _convert(self, detector, result, top_k=None):
        """Keep the original three transfer entries and all sorting semantics."""
        if result.boxes is None or len(result.boxes) == 0:
            return []
        if getattr(result, "masks", None) is not None:
            self._fallback(ValueError("a1 mask geometry requires the original converter"))
            return self._original_convert(result, top_k=top_k)
        boxes = result.boxes.xyxy.detach().cpu().numpy().tolist()
        confs = result.boxes.conf.detach().cpu().numpy().tolist()
        classes = result.boxes.cls.detach().cpu().numpy().astype(int).tolist()
        candidates = []
        names = detector.names
        for (x1, y1, x2, y2), conf, cls_id in zip(boxes, confs, classes):
            # tolist returns the same exact Python floats as baseline float(v).
            width = max(1.0, x2 - x1)
            height = max(1.0, y2 - y1)
            candidates.append(BallDetection(
                center=np.array([(x1 + x2) * 0.5, (y1 + y2) * 0.5], dtype=np.float64),
                radius_px=float(0.5 * max(width, height)),
                score=float(conf),
                bbox=(int(round(x1)), int(round(y1)), int(round(width)), int(round(height))),
                source="yolo", class_id=int(cls_id), class_name=str(names.get(int(cls_id), "")),
            ))
        # Python sort is stable, including equal scores. Do not move top_k earlier.
        candidates.sort(key=lambda item: item.score, reverse=True)
        self.converted_results += 1
        return candidates[:top_k] if top_k is not None and top_k > 0 else candidates

    def _pack_final_results(self, results):
        """Copy six-column final results once; leave original objects untouched."""
        import torch

        if not isinstance(results, list):
            raise ValueError("a2 supports the non-streaming Results list only")
        tensors = []
        for result in results:
            if getattr(result, "masks", None) is not None:
                raise ValueError("a2 mask results require the original path")
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            data = boxes.data
            if not isinstance(data, torch.Tensor) or data.ndim != 2 or data.shape[1] != 6:
                raise ValueError("a2 requires ordinary untracked six-column Boxes")
            if data.dtype != torch.float32:
                raise ValueError("a2 requires frozen FP32 results")
            if tensors and (data.device != tensors[0].device or data.dtype != tensors[0].dtype):
                raise ValueError("a2 cannot pack mixed devices or dtypes")
            tensors.append(data.detach())
        total_rows = sum(int(t.shape[0]) for t in tensors)
        if not total_rows:
            return results
        # cat is after original NMS and image scaling; no conf/IoU/top-k edits.
        packed = torch.cat(tensors, dim=0)
        host = packed.cpu()  # blocking copy; lifetime safely owns each returned slice
        output = []
        start = 0
        for result in results:
            if result.boxes is None:
                output.append(result)
                continue
            count = len(result.boxes)
            new_result = copy.copy(result)
            new_boxes = copy.copy(result.boxes)
            new_boxes.data = host[start:start + count]
            # Boxes normally has xywh/xyxyn/xywhn cached properties. A shallow
            # copy of already-evaluated caches must not retain CUDA storage.
            for cached_name in ("xywh", "xyxyn", "xywhn"):
                vars(new_boxes).pop(cached_name, None)
            new_result.boxes = new_boxes
            output.append(new_result)
            start += count
        self.packed_batches += 1
        self.packed_rows += total_rows
        if packed.is_cuda:
            self.d2h_calls += 1
            self.d2h_bytes += int(packed.numel() * packed.element_size())
        return output

    def describe(self):
        return {
            "requested": self.requested, "effective": "a0" if self.restored else self.effective,
            "available": self.requested != "a3", "restored": self.restored,
            "fallback_count": self.fallback_count, "last_error": self.last_error,
            "predict_calls": self.calls, "converted_results": self.converted_results,
            "packed_batches": self.packed_batches, "packed_rows": self.packed_rows,
            "d2h_calls": self.d2h_calls, "d2h_bytes": self.d2h_bytes,
            "last_pack_wall_ms": self.last_pack_wall_ms, "pack_wall_ms_total": self.pack_wall_ms_total,
            "pack_wall_scope": "cat + blocking CPU copy + Result/Boxes shallow copies; not exclusive GPU time",
            "nms": "original predictor unchanged", "top_k": "original stable sort then slice",
        }

    def restore(self):
        if self.restored:
            return
        for obj, name, old, installed in reversed(self._patches):
            if vars(obj).get(name, _ABSENT) is not installed:
                raise RuntimeError("{} changed after E04 install; refusing to overwrite it".format(name))
            if old is _ABSENT:
                delattr(obj, name)
            else:
                setattr(obj, name, old)
        self._patches.clear()
        if getattr(self.detector, "_e04_postprocess_handle", None) is self:
            delattr(self.detector, "_e04_postprocess_handle")
        self.restored = True


def install(detector, variant="a0"):
    """Install one reversible variant on this detector/model instance only."""
    return PostprocessHandle(detector, variant)
