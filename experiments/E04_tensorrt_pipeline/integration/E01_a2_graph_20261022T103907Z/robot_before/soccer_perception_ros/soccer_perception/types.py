"""定位、跟踪和 ROS 输出共用的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from pathlib import Path

import numpy as np


def _vec_or_none(value: np.ndarray | None) -> list[float] | None:
    """把 NumPy 向量转换成 JSON 友好的 float list。"""

    if value is None:
        return None
    return [float(v) for v in np.asarray(value, dtype=np.float64).reshape(-1)]


def _finite_float_or_none(value: object) -> float | None:
    """Convert numeric values to finite JSON floats; non-finite values become None."""

    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(converted):
        return None
    return converted


def json_safe(value: Any) -> Any:
    """Recursively convert common NumPy values into JSON-friendly primitives."""

    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float):
        return _finite_float_or_none(value)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


@dataclass
class CameraIntrinsics:
    """双目几何计算所需的相机参数。"""

    # K 是左相机内参矩阵；baseline_m 是左右目基线，单位米。
    K: np.ndarray
    baseline_m: float
    # fps 和 image_size 记录相机采集参数。
    fps: float
    image_size: tuple[int, int]


@dataclass
class BallDetection:
    """单目足球检测结果。"""

    # center/radius_px 是后续双目匹配和三角化使用的核心几何量。
    center: np.ndarray
    radius_px: float
    score: float
    # bbox/source/class_* 用于可视化、日志和前端调试。
    bbox: tuple[int, int, int, int]
    source: str = "yolo"
    class_id: int | None = None
    class_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换成可直接放进 JSON frame packet 的字典。"""

        return {
            "cx": float(self.center[0]),
            "cy": float(self.center[1]),
            "radius": float(self.radius_px),
            "score": float(self.score),
            "bbox": [int(v) for v in self.bbox],
            "source": self.source,
            "class_id": self.class_id,
            "class_name": self.class_name,
        }


@dataclass
class Ball3DMeasurement:
    """Single-frame camera FLU 3D ball measurement.

    The position uses camera FLU axes: [X forward, Y left, Z up].
    This object describes measurement validity only; control payload validity is
    still derived from tracker state.
    """

    position_camera_m: np.ndarray | None
    valid: bool
    confidence: float
    source: str
    quality: float = 0.0
    reject_reasons: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source = str(self.source or "none")
        self.confidence = self._clamp_unit(self.confidence)
        self.quality = self._finite_or_zero(self.quality)
        self.reject_reasons = [str(reason) for reason in self.reject_reasons if str(reason)]
        self.diagnostics = dict(self.diagnostics)

        if self.position_camera_m is None:
            self.valid = False
            self.confidence = 0.0
            return

        position = np.asarray(self.position_camera_m, dtype=np.float64).reshape(-1)
        if position.size < 3 or not np.all(np.isfinite(position[:3])):
            self.position_camera_m = None
            self.valid = False
            self.confidence = 0.0
            if "triangulation_non_finite" not in self.reject_reasons:
                self.reject_reasons.append("triangulation_non_finite")
            return

        self.position_camera_m = position[:3].copy()
        self.valid = bool(self.valid)
        if not self.valid:
            self.position_camera_m = None
            self.confidence = 0.0
            if not self.reject_reasons:
                self.reject_reasons.append("invalid_measurement")

    @classmethod
    def valid_measurement(
        cls,
        position_camera_m: np.ndarray,
        *,
        source: str,
        confidence: float = 1.0,
        quality: float = 0.0,
        diagnostics: dict[str, Any] | None = None,
    ) -> "Ball3DMeasurement":
        return cls(
            position_camera_m=position_camera_m,
            valid=True,
            confidence=confidence,
            source=source,
            quality=quality,
            reject_reasons=[],
            diagnostics={} if diagnostics is None else diagnostics,
        )

    @classmethod
    def invalid(
        cls,
        *,
        source: str,
        reject_reasons: list[str],
        diagnostics: dict[str, Any] | None = None,
        quality: float = 0.0,
    ) -> "Ball3DMeasurement":
        reasons = [str(reason) for reason in reject_reasons if str(reason)]
        return cls(
            position_camera_m=None,
            valid=False,
            confidence=0.0,
            source=source,
            quality=quality,
            reject_reasons=reasons or ["invalid_measurement"],
            diagnostics={} if diagnostics is None else diagnostics,
        )

    def position_or_none(self) -> np.ndarray | None:
        if not self.valid or self.position_camera_m is None:
            return None
        return self.position_camera_m.copy()

    def to_dict(self) -> dict[str, Any]:
        position = None
        if self.valid and self.position_camera_m is not None:
            position = {
                "x_front": float(self.position_camera_m[0]),
                "y_left": float(self.position_camera_m[1]),
                "z_up": float(self.position_camera_m[2]),
            }
        return {
            "valid": bool(self.valid),
            "source": self.source,
            "confidence": float(self.confidence),
            "quality": float(self.quality),
            "position_camera_m": position,
            "reject_reasons": list(self.reject_reasons),
            "diagnostics": json_safe(self.diagnostics),
        }

    @staticmethod
    def _finite_or_zero(value: object) -> float:
        converted = _finite_float_or_none(value)
        return 0.0 if converted is None else converted

    @classmethod
    def _clamp_unit(cls, value: object) -> float:
        converted = cls._finite_or_zero(value)
        return float(max(0.0, min(1.0, converted)))


@dataclass
class StereoFrame:
    """输入源输出的一对同步左右目图像。"""

    timestamp: float
    left: np.ndarray
    right: np.ndarray
    frame_idx: int = 0
    zed_xyzrgba: Any | None = None


@dataclass
class TrackState:
    """3D tracker output state.

    The active camera-frame pipeline uses camera FLU axes:
    [X forward, Y left, Z up].
    """

    # p/v 分别是位置和速度，统一使用 camera FLU frame。
    p: np.ndarray
    v: np.ndarray
    last_t: float
    # coasting=True 表示当前状态由预测维持，而不是当前帧测量直接更新。
    initialized: bool = False
    frames_since_measurement: int = 0
    coasting: bool = False

    def copy(self) -> "TrackState":
        """深拷贝 NumPy 数组，防止调用方持有可变内部状态。"""

        return TrackState(
            p=self.p.copy(),
            v=self.v.copy(),
            last_t=float(self.last_t),
            initialized=bool(self.initialized),
            frames_since_measurement=int(self.frames_since_measurement),
            coasting=bool(self.coasting),
        )

    def to_dict(self) -> dict[str, Any]:
        """转换成 JSON 友好的 tracker 明细。"""

        return {
            "position_m": _vec_or_none(self.p) if self.initialized else None,
            "velocity_mps": _vec_or_none(self.v) if self.initialized else None,
            "last_t": float(self.last_t),
            "initialized": bool(self.initialized),
            "frames_since_measurement": int(self.frames_since_measurement),
            "coasting": bool(self.coasting),
        }


@dataclass
class FramePacket:
    """每帧定位结果，供 ROS 发布与可选可视化使用。"""

    # 基本帧信息和实时性能。
    frame_idx: int
    timestamp: float
    status: str
    fps: float
    det_ms: float

    # 左右目检测和双目几何结果。3D camera 字段统一使用 FLU [front, left, up]。
    left_det: BallDetection | None
    right_det: BallDetection | None
    ball_3d_measurement: Ball3DMeasurement
    camera_measurement_m: np.ndarray | None
    camera_track_state: TrackState
    camera_position_m: np.ndarray | None
    camera_velocity_mps: np.ndarray | None
    camera_track_mode: str
    camera_track_confidence: float
    disparity_px: float
    vertical_delta_px: float
    detector_name: str
    baseline_m: float
    camera_intrinsics: dict[str, Any] = field(default_factory=dict)


    candidate_diagnostics: dict[str, Any] = field(default_factory=dict)
    short_loss_tolerated: bool = False
    short_loss_age_s: float | None = None
    short_loss_timeout_s: float = 0.0


@dataclass
class BackendConfig:
    """YAML 加载后的运行时数据；仅定义字段类型，不保存任何配置默认值。"""

    zed_resolution: str
    zed_fps: int
    zed_depth_mode: str
    zed_open_retries: int
    zed_open_retry_delay: float
    zed_brightness: int | None
    zed_contrast: int | None
    zed_hue: int | None
    zed_saturation: int | None
    zed_sharpness: int | None
    zed_gain: int | None
    zed_exposure: int | None
    zed_whitebalance_temperature: int | None
    zed_led_status: int | None
    det_conf: float
    yolo_model: Path
    yolo_class_ids: str
    yolo_top_k: int
    imgsz: int
    device: str
    half: bool
    yolo_tensorrt: bool
    yolo_engine_path: Path | None
    yolo_trt_batch: int
    yolo_trt_dynamic: bool
    yolo_trt_workspace_gb: float | None
    max_vertical_delta_px: float
    vertical_radius_factor: float
    short_loss_tolerance_enabled: bool
    short_loss_tolerance_s: float
    max_coast_frames: int
    max_coast_time_s: float
    velocity_decay: float
    candidate_yolo_score_weight: float
    candidate_vertical_penalty: float
    candidate_prediction_penalty: float
    candidate_disparity_jump_penalty: float
    candidate_max_radius_ratio: float
    candidate_bbox_gate_enabled: bool
    candidate_bbox_max_area_ratio: float
    candidate_bbox_min_area_px: float
    candidate_bbox_min_aspect_ratio: float
    candidate_bbox_max_aspect_ratio: float
    candidate_bbox_clip_to_image: bool
    candidate_bbox_pair_max_size_ratio: float
    candidate_min_radius_px: float | None
    candidate_max_radius_px: float | None
    candidate_min_depth_m: float
    candidate_max_depth_m: float
    candidate_expected_ball_radius_m: float
    candidate_radius_consistency_enabled: bool
    candidate_radius_consistency_tolerance_ratio: float
    candidate_radius_consistency_hard_gate: bool
    candidate_prediction_3d_penalty: float
    candidate_max_3d_jump_m: float | None
    candidate_max_speed_mps: float | None
    candidate_score_gate_enabled: bool
    candidate_min_yolo_score: float | None
    deploy_packet_rate_hz: float
    deploy_send_invalid_state: bool
    disable_cudnn: bool
    zed_viser_enabled: bool
    zed_viser_host: str
    zed_viser_port: int
    zed_viser_show_image: bool
    zed_viser_show_point_cloud: bool
    zed_viser_image_stride: int
    zed_viser_pc_stride: int
    zed_viser_pc_max_points: int
    zed_viser_pc_point_size: float
    zed_viser_max_depth_m: float
    zed_viser_ball_radius_m: float
    frame_id: str
    publish_json: bool
    publish_invalid_position: bool
    position_topic: str
    valid_topic: str
    status_topic: str
    json_topic: str
