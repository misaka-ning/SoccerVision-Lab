"""Explicit E02 experimental predictor selection; defaults retain production.

Environment options are read once at detector load. Each predictor owns its
buffers and NMS callback. No global Ultralytics or torchvision op is replaced.
"""
from __future__ import annotations

import os
from functools import partial


def experimental_predictor_class():
    post = os.environ.get("SOCCER_YOLO_POSTPROCESS", "baseline")
    nms = os.environ.get("SOCCER_YOLO_NMS", "torch")
    pre = os.environ.get("SOCCER_YOLO_PREPROCESS", "baseline")
    if post not in {"baseline", "single_class"}:
        raise ValueError("SOCCER_YOLO_POSTPROCESS must be baseline or single_class")
    if nms not in {"torch", "numpy", "torchvision"}:
        raise ValueError("SOCCER_YOLO_NMS must be torch, numpy or torchvision")
    if pre not in {"baseline", "reuse"}:
        raise ValueError("SOCCER_YOLO_PREPROCESS must be baseline or reuse")
    if nms != "torch" and post != "single_class":
        raise ValueError("Alternative NMS requires single_class postprocessing")
    if post == "baseline" and pre == "baseline":
        return None

    from ultralytics.models.yolo.detect.predict import DetectionPredictor
    base = DetectionPredictor
    if post == "single_class":
        from soccer_perception.adapters.fast_postprocess import make_fast_predictor_class
        callback = None
        if nms != "torch":
            from soccer_perception.adapters.nms_backends import dispatch_nms
            callback = partial(dispatch_nms, backend=nms)
        base = make_fast_predictor_class(nms=callback)
    if pre == "baseline":
        return base

    from soccer_perception.adapters.fast_preprocess import ReusablePreprocessor

    class ReusablePredictor(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._reusable_preprocessor = ReusablePreprocessor()

        def preprocess(self, images):
            if isinstance(images, (list, tuple)) and self._reusable_preprocessor.supports(images):
                return self._reusable_preprocessor.for_predictor(self, images)
            return super().preprocess(images)

    return ReusablePredictor
