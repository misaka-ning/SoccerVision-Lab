"""双目图像输入源。

FrameSource 统一输出 StereoFrame；当前生产实现只保留真实 ZED/ZED Mini
实时流。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

import cv2
import numpy as np

from soccer_perception.types import BackendConfig
from soccer_perception.types import CameraIntrinsics, StereoFrame


class FrameSource(ABC):
    """所有帧源的统一接口。"""

    @abstractmethod
    def open(self) -> CameraIntrinsics:
        """打开资源并返回本次输入使用的相机内参。"""

        raise NotImplementedError

    @abstractmethod
    def read(self) -> StereoFrame | None:
        """读取下一对左右目帧；输入耗尽时返回 None。"""

        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """释放相机、文件句柄等底层资源。"""

        raise NotImplementedError


class ZedFrameSource(FrameSource):
    """通过 Stereolabs ZED SDK 读取实时左右目 RGB 图像。"""

    _VIDEO_SETTING_FIELDS = (
        ("zed_brightness", "BRIGHTNESS"),
        ("zed_contrast", "CONTRAST"),
        ("zed_hue", "HUE"),
        ("zed_saturation", "SATURATION"),
        ("zed_sharpness", "SHARPNESS"),
        ("zed_gain", "GAIN"),
        ("zed_exposure", "EXPOSURE"),
        ("zed_whitebalance_temperature", "WHITEBALANCE_TEMPERATURE"),
        ("zed_led_status", "LED_STATUS"),
    )

    def __init__(self, config: BackendConfig):
        self.config = config
        self._sl = None
        self._cam = None
        self._runtime = None
        self._left_mat = None
        self._right_mat = None
        self._xyzrgba_mat = None
        self._start = 0.0
        self._idx = 0
        self._depth_enabled = False

    def open(self) -> CameraIntrinsics:
        """打开 ZED 相机，并从 SDK 读取当前分辨率下的内参和基线。"""

        try:
            import pyzed.sl as sl
        except ModuleNotFoundError as exc:
            raise RuntimeError("ZED SDK Python API is not available: import pyzed.sl failed.") from exc

        resolution = {
            "HD2K": sl.RESOLUTION.HD2K,
            "HD1080": sl.RESOLUTION.HD1080,
            "HD720": sl.RESOLUTION.HD720,
            "VGA": sl.RESOLUTION.VGA,
        }[self.config.zed_resolution]
        depth_mode = {
            "NONE": sl.DEPTH_MODE.NONE,
            "PERFORMANCE": sl.DEPTH_MODE.PERFORMANCE,
            "QUALITY": sl.DEPTH_MODE.QUALITY,
            "ULTRA": sl.DEPTH_MODE.ULTRA,
            "NEURAL": getattr(sl.DEPTH_MODE, "NEURAL", sl.DEPTH_MODE.QUALITY),
        }[self.config.zed_depth_mode if self.config.zed_viser_enabled and self.config.zed_viser_show_point_cloud else "NONE"]
        init = sl.InitParameters(
            camera_resolution=resolution,
            camera_fps=self.config.zed_fps,
            depth_mode=depth_mode,
            coordinate_units=sl.UNIT.METER,
        )
        if hasattr(sl, "COORDINATE_SYSTEM"):
            # Viser converts SDK IMAGE coordinates to camera FLU.
            coordinate_system = getattr(sl.COORDINATE_SYSTEM, "IMAGE", None)
            if coordinate_system is not None:
                init.coordinate_system = coordinate_system
        cam = sl.Camera()
        status = None
        for attempt in range(max(1, self.config.zed_open_retries)):
            # ZED 设备初始化偶尔会被 USB/SDK 状态影响，保留有限重试。
            status = cam.open(init)
            if status == sl.ERROR_CODE.SUCCESS:
                break
            cam.close()
            if attempt + 1 < self.config.zed_open_retries:
                time.sleep(self.config.zed_open_retry_delay)
                cam = sl.Camera()
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Could not open ZED camera: {status}")
        self._cam = cam  # Allow cleanup if subsequent initialization fails.
        self._apply_video_settings(cam, sl)

        info = cam.get_camera_information()
        calib = info.camera_configuration.calibration_parameters
        left = calib.left_cam
        # 后续三角化只需要左相机内参和左右目基线。
        k = np.array(
            [
                [float(left.fx), 0.0, float(left.cx)],
                [0.0, float(left.fy), float(left.cy)],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        fps = float(getattr(info.camera_configuration, "fps", 0.0) or 0.0)
        resolution_info = getattr(info.camera_configuration, "resolution", None)
        if resolution_info is not None:
            image_size = (int(resolution_info.width), int(resolution_info.height))
        else:
            # 旧版 SDK 可能不暴露 resolution 字段，使用请求分辨率兜底。
            image_size = {
                "HD2K": (2208, 1242),
                "HD1080": (1920, 1080),
                "HD720": (1280, 720),
                "VGA": (672, 376),
            }[self.config.zed_resolution]

        self._sl = sl
        self._cam = cam
        self._runtime = sl.RuntimeParameters()
        self._left_mat = sl.Mat()
        self._right_mat = sl.Mat()
        self._depth_enabled = bool(self.config.zed_viser_enabled and self.config.zed_viser_show_point_cloud and self.config.zed_depth_mode != "NONE")
        self._xyzrgba_mat = sl.Mat() if self._depth_enabled else None
        self._start = time.perf_counter()
        self._idx = 0
        return CameraIntrinsics(K=k, baseline_m=abs(float(calib.get_camera_baseline())), fps=fps, image_size=image_size)

    def read(self) -> StereoFrame | None:
        """抓取一帧 ZED 左右目图像并转换为 OpenCV BGR。"""

        if self._sl is None or self._cam is None or self._runtime is None:
            raise RuntimeError("ZedFrameSource.open() must be called before read().")
        status = self._cam.grab(self._runtime)
        if status != self._sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"ZED grab failed: {status}")
        self._cam.retrieve_image(self._left_mat, self._sl.VIEW.LEFT)
        self._cam.retrieve_image(self._right_mat, self._sl.VIEW.RIGHT)
        cloud = None
        if self._depth_enabled and self._xyzrgba_mat is not None:
            status = self._cam.retrieve_measure(self._xyzrgba_mat, self._sl.MEASURE.XYZRGBA)
            if status == self._sl.ERROR_CODE.SUCCESS:
                cloud = self._xyzrgba_mat
        left_bgra = self._left_mat.get_data()
        right_bgra = self._right_mat.get_data()
        # ZED SDK 输出 BGRA；检测器和渲染统一使用 BGR。
        left = cv2.cvtColor(left_bgra, cv2.COLOR_BGRA2BGR)
        right = cv2.cvtColor(right_bgra, cv2.COLOR_BGRA2BGR)
        frame = StereoFrame(
            timestamp=time.perf_counter() - self._start,
            left=left,
            right=right,
            frame_idx=self._idx,
            zed_xyzrgba=cloud,
        )
        self._idx += 1
        return frame

    def close(self) -> None:
        """关闭 ZED 相机句柄。"""

        if self._cam is not None:
            self._cam.close()
        self._cam = None

    def _apply_video_settings(self, cam: Any, sl: Any) -> None:
        """Apply optional ZED image controls after the camera opens."""

        video_settings = getattr(sl, "VIDEO_SETTINGS", None)
        if video_settings is None:
            return
        for config_name, sdk_name in self._VIDEO_SETTING_FIELDS:
            value = getattr(self.config, config_name)
            if value is None:
                continue
            setting = getattr(video_settings, sdk_name, None)
            if setting is None:
                continue
            cam.set_camera_settings(setting, int(value))
