"""双目几何工具。"""

from __future__ import annotations

import numpy as np

from soccer_perception.core.coordinates import optical_to_camera_flu
from soccer_perception.types import BallDetection, CameraIntrinsics


class StereoTriangulator:
    """基于已校正左右目中心点的简单双目三角化器。"""

    def __init__(
        self,
        intrinsics: CameraIntrinsics,
        max_vertical_delta_px: float = 18.0,
        vertical_radius_factor: float = 0.75,
    ):
        self.intrinsics = intrinsics
        # 竖直方向误差门限用于过滤左右目误匹配。
        self.max_vertical_delta_px = max_vertical_delta_px
        self.vertical_radius_factor = vertical_radius_factor

    def triangulate_camera(self, left_det: BallDetection, right_det: BallDetection) -> np.ndarray | None:
        """在 camera FLU 坐标系下计算 3D 点；视差过小时返回 None。"""

        disparity = float(left_det.center[0] - right_det.center[0])
        # 已极线校正的双目中，深度 z = fx * baseline / disparity。
        if disparity <= 0.5:
            return None
        k = self.intrinsics.K
        fx, fy, cx, cy = float(k[0, 0]), float(k[1, 1]), float(k[0, 2]), float(k[1, 2])
        z = fx * self.intrinsics.baseline_m / disparity
        x = (float(left_det.center[0]) - cx) * z / fx
        y = (float(left_det.center[1]) - cy) * z / fy
        return optical_to_camera_flu(np.array([x, y, z], dtype=np.float64))

    def disparity_px(self, left_det: BallDetection | None, right_det: BallDetection | None) -> float:
        """计算左右目水平视差，缺失检测时返回 NaN。"""

        if left_det is None or right_det is None:
            return float("nan")
        return float(left_det.center[0] - right_det.center[0])

    def vertical_delta_px(self, left_det: BallDetection | None, right_det: BallDetection | None) -> float:
        """计算左右目检测中心的竖直差，缺失检测时返回 NaN。"""

        if left_det is None or right_det is None:
            return float("nan")
        return abs(float(left_det.center[1] - right_det.center[1]))

    def is_vertical_match(self, left_det: BallDetection, right_det: BallDetection) -> bool:
        """检查左右检测是否可能是同一个球。"""

        limit = max(
            self.max_vertical_delta_px,
            self.vertical_radius_factor * max(left_det.radius_px, right_det.radius_px),
        )
        return self.vertical_delta_px(left_det, right_det) < limit
