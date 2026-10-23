"""Coordinate conversion helpers used at sensor boundaries."""

from __future__ import annotations

import numpy as np


def optical_to_camera_flu(point: np.ndarray) -> np.ndarray:
    """相机光学坐标转换到 camera FLU 坐标。

    Optical: X right, Y down, Z forward.
    FLU:     X forward, Y left,  Z up.
    """

    p = np.asarray(point, dtype=np.float64)
    return np.array([p[2], -p[0], -p[1]], dtype=np.float64)


def camera_flu_to_optical(point: np.ndarray) -> np.ndarray:
    """camera FLU 坐标转换回相机光学坐标。"""

    p = np.asarray(point, dtype=np.float64)
    return np.array([-p[1], -p[2], p[0]], dtype=np.float64)
