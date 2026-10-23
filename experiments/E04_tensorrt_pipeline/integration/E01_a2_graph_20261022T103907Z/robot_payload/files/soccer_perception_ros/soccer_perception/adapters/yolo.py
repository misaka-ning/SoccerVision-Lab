"""足球检测器适配层。

生产 pipeline 只使用 Ultralytics YOLO。检测器仍返回统一的
BallDetection，方便后续双目几何、候选选择和渲染复用。
"""

from __future__ import annotations

import json
import os
import sys
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from sys import version_info

import cv2
import numpy as np

from soccer_perception.types import BallDetection


def _install_torchvision_nms_fallback() -> None:
    """Use a pure torch NMS when torchvision's compiled ops are unavailable."""

    try:
        import torch
        import torchvision
    except ModuleNotFoundError:
        return

    try:
        torchvision.ops.nms(torch.zeros((1, 4)), torch.ones(1), 0.5)
        return
    except Exception as exc:
        print(f"torchvision.ops.nms unavailable, using pure torch fallback: {exc}", file=sys.stderr)

    def nms_fallback(boxes, scores, iou_threshold):
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

    torchvision.ops.nms = nms_fallback
    try:
        import ultralytics.utils.ops as ultralytics_ops

        ultralytics_ops.torchvision.ops.nms = nms_fallback
    except Exception:
        pass


class BallDetector(ABC):
    """检测器统一接口。"""

    name: str

    @abstractmethod
    def load(self) -> None:
        """加载模型或初始化资源；轻量检测器可以为空实现。"""

        raise NotImplementedError

    @abstractmethod
    def detect(self, frame: np.ndarray) -> BallDetection | None:
        """在单张 BGR 图像中检测足球，找不到时返回 None。"""

        raise NotImplementedError

    def detect_candidates(self, frame: np.ndarray, top_k: int | None = None) -> list[BallDetection]:
        """返回候选列表；默认兼容旧的单目标检测器。"""

        det = self.detect(frame)
        return [] if det is None else [det]

    def detect_candidates_batch(
        self,
        frames: Sequence[np.ndarray],
        top_k: int | None = None,
    ) -> list[list[BallDetection]]:
        """批量返回候选列表；默认逐帧调用，供不支持 batch 的检测器兼容。"""

        return [self.detect_candidates(frame, top_k=top_k) for frame in frames]


class YoloBallDetector(BallDetector):
    """Ultralytics YOLO 检测器适配器。"""

    def __init__(
        self,
        model_path: Path,
        conf: float,
        imgsz: int,
        device: str | None,
        class_ids: list[int],
        half: bool,
        tensorrt: bool = False,
        engine_path: Path | None = None,
        trt_batch: int = 2,
        trt_dynamic: bool = False,
        trt_workspace_gb: float | None = None,
        optimization: str = "none",
    ):
        self.model_path = model_path
        self.conf = conf
        self.imgsz = imgsz
        self.device = device
        self.class_ids = class_ids
        self.half = half
        self.tensorrt = tensorrt or model_path.suffix.lower() == ".engine"
        self.engine_path = engine_path
        self.trt_batch = max(1, int(trt_batch))
        self.trt_dynamic = trt_dynamic
        self.trt_workspace_gb = trt_workspace_gb
        from soccer_perception.optimizations import variants_for_mode

        variants_for_mode(optimization)
        self.optimization = optimization
        self._optimization_handle = None
        self._last_optimization_status = None
        self._optimization_warning_emitted = False
        self.model = None
        self.runtime_model_path = model_path
        self.names: dict[int, str] = {}
        backend = "tensorrt" if self.tensorrt else "pytorch"
        self.name = f"yolo-{backend}:{model_path.name}"

    def load(self) -> None:
        """延迟加载 YOLO 模型，避免只导入模块时触发重依赖。"""

        self._check_optimization_settings()
        if self.model is not None or self._optimization_handle is not None:
            self.close()
        self._optimization_warning_emitted = False
        self._last_optimization_status = None
        try:
            from ultralytics import YOLO
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Ultralytics is not installed in this Python environment. "
                f"python={sys.executable}. "
                "For live ZED + YOLO, start the backend with "
                "`ros2 launch soccer_perception_ros soccer_perception.launch.py` or install ultralytics into this exact interpreter."
            ) from exc
        _install_torchvision_nms_fallback()
        load_path = self._prepare_model_path()
        self.runtime_model_path = load_path
        if load_path != self.model_path:
            self.name = f"yolo-tensorrt:{load_path.name}"
        if load_path.suffix.lower() == ".engine":
            self.model = YOLO(str(load_path), task="detect")
        else:
            self.model = YOLO(str(load_path))
        from soccer_perception.adapters.optimization import experimental_predictor_class

        predictor_class = experimental_predictor_class()
        if predictor_class is not None:
            # Configure before reading model.names: Ultralytics 8.3.159 creates
            # the TensorRT predictor while resolving names, before predict().
            setup_overrides = dict(self.model.overrides)
            setup_overrides.update(imgsz=self.imgsz, conf=self.conf, verbose=False)
            if self.class_ids:
                setup_overrides["classes"] = self.class_ids
            if load_path.suffix.lower() != ".engine":
                if self.device:
                    setup_overrides["device"] = self.device
                setup_overrides["half"] = self.half
            self.model.predictor = predictor_class(
                overrides=setup_overrides, _callbacks=self.model.callbacks,
            )
            self.model.predictor.setup_model(model=self.model.model, verbose=False)
        self.names = self._safe_model_names()
        if self.optimization != "none":
            try:
                self._initialize_optimizations()
            except BaseException:
                # Installation and discarded startup work never become a ROS
                # result. Release any owned context/stream on partial failure.
                try:
                    self.close()
                except Exception as cleanup_error:
                    print("E04 optimization cleanup failed: %s" % cleanup_error, file=sys.stderr)
                raise

    def _check_optimization_settings(self) -> None:
        if self.optimization == "none":
            return
        defaults = {"SOCCER_YOLO_POSTPROCESS": "baseline", "SOCCER_YOLO_NMS": "torch",
                    "SOCCER_YOLO_PREPROCESS": "baseline"}
        conflicts = {key: os.environ[key] for key, default in defaults.items()
                     if os.environ.get(key, default) != default}
        if conflicts:
            raise ValueError("yolo_optimization cannot be combined with legacy predictor options: %r" % conflicts)

    def _prediction_kwargs(self) -> dict:
        kwargs = {"conf": self.conf, "imgsz": self.imgsz, "verbose": False}
        if self.class_ids:
            kwargs["classes"] = self.class_ids
        if self.device and self.runtime_model_path.suffix.lower() != ".engine":
            kwargs["device"] = self.device
        if self.half and self.runtime_model_path.suffix.lower() != ".engine":
            kwargs["half"] = True
        if self.optimization != "none":
            # Keep the E04 letterbox contract. Baseline/legacy kwargs retain
            # their original behavior when the new switch is disabled.
            kwargs["rect"] = False
        return kwargs

    def _initialize_optimizations(self) -> None:
        from soccer_perception.optimizations import install_pipeline, variants_for_mode

        images = [np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
                  for _ in range(self.trt_batch)]
        kwargs = self._prediction_kwargs()
        # Initialize the real predictor/backend before attaching any hooks.
        # Both this baseline result and the capture/warmup result are discarded.
        self.model.predict(images, **kwargs)
        self._optimization_handle = install_pipeline(self, variants_for_mode(self.optimization))
        self.model.predict(images, **kwargs)
        self._optimization_handle.synchronize()
        print("E04 optimization initialized: " + json.dumps(self.optimization_status(), ensure_ascii=False),
              file=sys.stderr)
        self._warn_optimization_fallback()

    def optimization_status(self) -> dict:
        state = self._last_optimization_status
        if self._optimization_handle is not None:
            state = self._optimization_handle.describe()
        return {"mode": self.optimization, "enabled": self._optimization_handle is not None, "state": state}

    def _warn_optimization_fallback(self) -> None:
        if self._optimization_handle is None or self._optimization_warning_emitted:
            return
        state = self._optimization_handle.describe()
        if any(value.get("fallback_count", 0) for value in state["components"].values()):
            self._optimization_warning_emitted = True
            print("E04 optimization fallback (original path retained): " +
                  json.dumps(self.optimization_status(), ensure_ascii=False), file=sys.stderr)

    def close(self) -> None:
        """Restore owned hooks before dropping model references; retry on error."""
        if self._optimization_handle is not None:
            self._optimization_handle.restore()
            self._last_optimization_status = self._optimization_handle.describe()
            self._optimization_handle = None
        self.model = None

    def _safe_model_names(self) -> dict[int, str]:
        """Read Ultralytics class names without forcing TensorRT setup to fail."""

        if self.model is None:
            return {}
        try:
            names = self.model.names
        except Exception as exc:
            print(f"Could not read YOLO class names; continuing without names: {exc}", file=sys.stderr)
            return {}
        if isinstance(names, dict):
            return {int(key): str(value) for key, value in names.items()}
        try:
            return {idx: str(value) for idx, value in enumerate(names)}
        except TypeError:
            return {}

    def _prepare_model_path(self) -> Path:
        """Inference never exports or overwrites a model."""
        if not self.tensorrt:
            return self.model_path
        from soccer_perception.model_artifacts import require_engine
        return require_engine(self)

    def build_engine(self, yolo_cls, *, force=False, adopt_existing=False) -> Path:
        from soccer_perception.model_artifacts import build_engine
        return build_engine(self, yolo_cls, force=force, adopt_existing=adopt_existing)

    def _trt_export_device(self) -> str | int:
        if not self.device:
            return 0
        device = str(self.device).strip()
        lowered = device.lower()
        if lowered == "cuda":
            return 0
        if lowered.startswith("cuda:") and lowered.split(":", 1)[1].isdigit():
            return lowered.split(":", 1)[1]
        return device

    def _trt_export_half(self) -> bool:
        if not self.half:
            return False
        try:
            import tensorrt as trt
        except Exception:
            if version_info < (3, 10):
                print(
                    "TensorRT version is unavailable before export. "
                    "Python <3.10 cannot install nvidia-modelopt>=0.44, so exporting FP32 TensorRT engine.",
                    file=sys.stderr,
                )
                return False
            return True
        major = int(str(trt.__version__).split(".", 1)[0])
        if major >= 11 and version_info < (3, 10):
            print(
                "TensorRT 11 FP16 export requires nvidia-modelopt>=0.44, "
                "which requires Python >=3.10. Falling back to FP32 engine export in this Python environment.",
                file=sys.stderr,
            )
            return False
        return True

    def detect(self, frame: np.ndarray) -> BallDetection | None:
        """运行 YOLO 推理，并返回最高置信度目标。"""
        candidates = self.detect_candidates(frame, top_k=1)
        return candidates[0] if candidates else None

    def detect_candidates(self, frame: np.ndarray, top_k: int | None = None) -> list[BallDetection]:
        """运行 YOLO 推理，并返回按置信度排序的候选列表。"""

        return self.detect_candidates_batch([frame], top_k=top_k)[0]

    def detect_candidates_batch(
        self,
        frames: Sequence[np.ndarray],
        top_k: int | None = None,
    ) -> list[list[BallDetection]]:
        """运行一次 YOLO batch 推理，并返回每张图的候选列表。"""

        if self.model is None:
            raise RuntimeError("YoloBallDetector.load() must be called before detect().")
        if not frames:
            return []
        results = self.model.predict(list(frames), **self._prediction_kwargs())
        self._warn_optimization_fallback()

        return [self._result_to_candidates(result, top_k=top_k) for result in results]

    def _result_to_candidates(self, result, top_k: int | None = None) -> list[BallDetection]:
        from soccer_perception.adapters.fast_postprocess import FastDetectionResult, rows_to_candidates

        if isinstance(result, FastDetectionResult):
            return rows_to_candidates(result.rows, names=self.names, top_k=top_k)
        if result.boxes is None or len(result.boxes) == 0:
            return []

        boxes = result.boxes.xyxy.detach().cpu().numpy()
        confs = result.boxes.conf.detach().cpu().numpy()
        classes = result.boxes.cls.detach().cpu().numpy().astype(int)
        polygons = []
        if getattr(result, "masks", None) is not None and result.masks is not None:
            polygons = result.masks.xy or []

        candidates: list[BallDetection] = []
        for idx, (xyxy, conf, cls_id) in enumerate(zip(boxes, confs, classes)):
            x1, y1, x2, y2 = [float(v) for v in xyxy]
            w = max(1.0, x2 - x1)
            h = max(1.0, y2 - y1)
            center = np.array([(x1 + x2) * 0.5, (y1 + y2) * 0.5], dtype=np.float64)
            radius = 0.5 * max(w, h)
            if idx < len(polygons) and len(polygons[idx]) >= 3:
                # segmentation 模型如果返回 mask，用 mask 质心/面积估计球心和半径。
                poly = polygons[idx].astype(np.float32)
                moments = cv2.moments(poly)
                area = abs(cv2.contourArea(poly))
                if abs(moments["m00"]) > 1e-6:
                    center = np.array([moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]], dtype=np.float64)
                if area > 1.0:
                    radius = float(np.sqrt(area / np.pi))

            det = BallDetection(
                center=center,
                radius_px=float(radius),
                score=float(conf),
                bbox=(int(round(x1)), int(round(y1)), int(round(w)), int(round(h))),
                source="yolo",
                class_id=int(cls_id),
                class_name=str(self.names.get(int(cls_id), "")),
            )
            candidates.append(det)
        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[:top_k] if top_k is not None and top_k > 0 else candidates


def parse_int_list(value: str) -> list[int]:
    """解析逗号分隔的类别 id；all/none/空字符串表示不过滤类别。"""

    if not value or value.lower() in {"all", "none"}:
        return []
    return [int(part.strip()) for part in value.split(",") if part.strip()]
