"""ROS 数据构造与按单调时钟固定周期输出。"""
from __future__ import annotations
import math
import time
from collections import deque
from typing import Any
from soccer_perception.types import FramePacket

BALL_CAMERA_STATE_COORDINATE_FRAME = "camera_flu"
BALL_CAMERA_STATE_POSITION_UNITS = "m"
BALL_CAMERA_STATE_AXES = {
    "x_m": "forward",
    "y_m": "left",
    "z_m": "up",
}


def build_ball_position_camera_payload(packet: FramePacket) -> dict[str, Any]:
    """构造与 ROS PointStamped 位置字段兼容的相机 FLU 坐标数据。"""

    valid = bool(packet.camera_position_m is not None and packet.camera_track_state.initialized)
    confidence = float(packet.camera_track_confidence) if valid else 0.0
    x_m = y_m = z_m = None
    if valid and packet.camera_position_m is not None:
        p = packet.camera_position_m
        x_m = float(p[0])
        y_m = float(p[1])
        z_m = float(p[2])

    return {
        "type": "ball_position_camera",
        "timestamp": float(packet.timestamp),
        "valid": valid,
        "confidence": confidence,
        "x_m": x_m,
        "y_m": y_m,
        "z_m": z_m,
    }

def build_ball_camera_diagnostics(packet: FramePacket) -> dict[str, Any]:
    """构造相机坐标系下的调试与状态诊断信息，与控制用的位置数据分开。"""

    raw = packet.camera_measurement_m
    velocity = packet.camera_velocity_mps
    measurement = packet.ball_3d_measurement
    measurement_diagnostics = measurement.to_dict().get("diagnostics", {})
    return {
        "frame_idx": int(packet.frame_idx),
        "status": packet.status,
        "track_mode": packet.camera_track_mode,
        "track_confidence": float(packet.camera_track_confidence),
        "coasting": bool(packet.camera_track_state.coasting),
        "frames_since_measurement": int(packet.camera_track_state.frames_since_measurement),
        "source": {
            "coordinate_frame": BALL_CAMERA_STATE_COORDINATE_FRAME,
            "axes": BALL_CAMERA_STATE_AXES,
            "position_units": BALL_CAMERA_STATE_POSITION_UNITS,
            "localization_source": "stereo_camera_track",
        },
        "measurement_source": measurement.source,
        "measurement_valid": bool(measurement.valid),
        "short_loss_tolerated": bool(packet.short_loss_tolerated),
        "short_loss_age_s": packet.short_loss_age_s,
        "short_loss_timeout_s": packet.short_loss_timeout_s,
        "measurement_confidence": float(measurement.confidence),
        "measurement_quality": float(measurement.quality),
        "measurement_reject_reasons": list(measurement.reject_reasons),
        "measurement_diagnostics": measurement_diagnostics,
        "camera_measurement_m": {
            "x_front": float(raw[0]),
            "y_left": float(raw[1]),
            "z_up": float(raw[2]),
        } if raw is not None else None,
        "camera_velocity_mps": {
            "x_front": float(velocity[0]),
            "y_left": float(velocity[1]),
            "z_up": float(velocity[2]),
        } if velocity is not None else None,
        "measurement_status": "ok" if measurement.valid else (measurement.reject_reasons[0] if measurement.reject_reasons else "invalid_measurement"),
        "detector": packet.detector_name,
        "disparity_px": float(packet.disparity_px),
        "vertical_delta_px": float(packet.vertical_delta_px),
        "candidate_selection": packet.candidate_diagnostics,
        "baseline_m": float(packet.baseline_m),
        "camera_intrinsics": dict(packet.camera_intrinsics),
        "fps": float(packet.fps),
        "det_ms": float(packet.det_ms),
    }

class OutputScheduler:
    """控制新结果的输出节奏，避免丢帧、等待时间累积漂移和超时后突发补发。"""

    def __init__(self, rate_hz: float):
        """根据目标输出频率计算周期，并准备发布时间记录。"""
        if not math.isfinite(rate_hz) or rate_hz <= 0.0:
            raise ValueError("deploy_packet_rate_hz must be finite and greater than zero")
        self.period = 1.0 / rate_hz
        self._deadline: float | None = None
        self._publish_times: deque[float] = deque()

    def start(self) -> None:
        """以单调时钟设置首次输出的目标时刻，避免系统时间调整影响调度。"""
        self._deadline = time.monotonic() + self.period

    def wait(self) -> None:
        """等待本次目标输出时刻，并计算下一次输出的目标时刻。"""
        if self._deadline is None:
            self.start()
        now = time.monotonic()
        processing_overrun = now > self._deadline
        while now < self._deadline:
            time.sleep(self._deadline - now)
            now = time.monotonic()
        # 正常唤醒抖动不累积到后续周期；处理超时或错过完整周期时，
        # 从当前时刻重新安排输出，避免为追赶旧计划而连续补发。
        self._deadline = (now if processing_overrun else self._deadline) + self.period
        if self._deadline <= now:
            self._deadline = now + self.period

    def record_publish(self) -> float:
        """记录本次发布时间，估算最近约五秒的实际输出频率，至少保留两个样本。"""
        now = time.monotonic()
        self._publish_times.append(now)
        while len(self._publish_times) > 2 and self._publish_times[0] < now - 5.0:
            self._publish_times.popleft()
        elapsed = now - self._publish_times[0]
        return (len(self._publish_times) - 1) / elapsed if elapsed > 0.0 else 0.0
