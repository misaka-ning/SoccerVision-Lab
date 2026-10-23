"""Optional Viser runtime visualization for the ZED pipeline."""

from __future__ import annotations

from typing import Any

import numpy as np

from soccer_perception.types import BackendConfig
from soccer_perception.core.coordinates import optical_to_camera_flu
from soccer_perception.types import BallDetection, FramePacket, StereoFrame


class ZedRuntimeVisualizer:
    """Display the current ZED frame, SDK point cloud, and tracked ball in Viser."""

    def __init__(self, config: BackendConfig):
        self.config = config
        self._server: Any | None = None
        self._gui_status: Any | None = None
        self._gui_show_pc: Any | None = None
        self._gui_show_img: Any | None = None

    def open(self) -> None:
        if not self.config.zed_viser_enabled:
            return
        try:
            import viser
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Viser viewer is enabled but the 'viser' package is not installed. "
                "Install it in the runtime Python environment with: pip install viser"
            ) from exc

        self._server = viser.ViserServer(
            host=str(self.config.zed_viser_host),
            port=int(self.config.zed_viser_port),
        )
        self._gui_status = self._server.gui.add_text("status", initial_value="starting...")
        self._gui_show_pc = self._server.gui.add_checkbox(
            "show point cloud",
            initial_value=bool(self.config.zed_viser_show_point_cloud),
        )
        self._gui_show_img = self._server.gui.add_checkbox(
            "show image",
            initial_value=bool(self.config.zed_viser_show_image),
        )
        print(
            "Viser viewer at "
            f"http://<robot-ip>:{int(self.config.zed_viser_port)} "
            f"(host={self.config.zed_viser_host})",
            flush=True,
        )

    def close(self) -> None:
        if self._server is None:
            return
        try:
            self._server.stop()
        finally:
            self._server = None

    def update(self, frame: StereoFrame, packet: FramePacket) -> None:
        if self._server is None:
            return

        show_img = self._gui_value(self._gui_show_img, self.config.zed_viser_show_image)
        show_pc = self._gui_value(self._gui_show_pc, self.config.zed_viser_show_point_cloud)
        if show_img:
            self._update_image(frame.left, packet.left_det)
        if show_pc:
            self._update_point_cloud(frame.zed_xyzrgba)
        self._update_ball_marker(packet)
        self._update_status(packet, point_cloud_available=frame.zed_xyzrgba is not None)

    def _update_image(self, left_bgr: np.ndarray, left_det: BallDetection | None) -> None:
        rgb = left_bgr[:, :, ::-1].copy()
        if left_det is not None and left_det.bbox is not None:
            self._draw_bbox(rgb, left_det.bbox)
        stride = max(1, int(self.config.zed_viser_image_stride))
        self._server.scene.set_background_image(rgb[::stride, ::stride], format="jpeg")

    def _update_point_cloud(self, xyzrgba_mat: Any | None) -> None:
        if xyzrgba_mat is None:
            return
        data = xyzrgba_mat.get_data()
        if data is None:
            return
        stride = max(1, int(self.config.zed_viser_pc_stride))
        sub = data[::stride, ::stride, :]
        raw_pts = sub[:, :, :3].reshape(-1, 3)
        rgba_f = sub[:, :, 3].reshape(-1).copy()

        finite = np.isfinite(raw_pts).all(axis=1)
        raw_depth = raw_pts[:, 2]
        valid = finite & (raw_depth > 0.0) & (raw_depth < float(self.config.zed_viser_max_depth_m))
        pts = raw_pts[valid]
        rgba_f = rgba_f[valid]
        if pts.shape[0] == 0:
            return

        pts = np.asarray([optical_to_camera_flu(point) for point in pts], dtype=np.float64)

        max_points = int(self.config.zed_viser_pc_max_points)
        if max_points > 0 and pts.shape[0] > max_points:
            idx = np.random.choice(pts.shape[0], max_points, replace=False)
            pts = pts[idx]
            rgba_f = rgba_f[idx]

        rgba_u8 = rgba_f.view(np.uint32)
        r = (rgba_u8 & 0x000000FF).astype(np.uint8)
        g = ((rgba_u8 & 0x0000FF00) >> 8).astype(np.uint8)
        b = ((rgba_u8 & 0x00FF0000) >> 16).astype(np.uint8)
        colors = np.stack([r, g, b], axis=1)

        self._server.scene.add_point_cloud(
            "/cloud",
            points=pts.astype(np.float32),
            colors=colors,
            point_size=float(self.config.zed_viser_pc_point_size),
        )

    def _update_ball_marker(self, packet: FramePacket) -> None:
        position = packet.camera_position_m
        if position is None or not packet.camera_track_state.initialized:
            self._server.scene.add_icosphere(
                "/ball",
                radius=0.001,
                color=(255, 140, 0),
                position=(0.0, 0.0, -10.0),
            )
            return

        self._server.scene.add_icosphere(
            "/ball",
            radius=float(self.config.zed_viser_ball_radius_m),
            color=(255, 140, 0),
            position=tuple(float(v) for v in position),
        )

    def _update_status(self, packet: FramePacket, *, point_cloud_available: bool) -> None:
        if self._gui_status is None:
            return
        p = packet.camera_position_m
        if p is None or not packet.camera_track_state.initialized:
            text = f"{packet.status} no ball"
        else:
            text = (
                f"{packet.status} xyz=({float(p[0]):+.2f},{float(p[1]):+.2f},{float(p[2]):+.2f}) "
                f"conf={float(packet.camera_track_confidence):.2f}"
            )
        if not point_cloud_available:
            text += " point_cloud=off"
        self._gui_status.value = text

    @staticmethod
    def _draw_bbox(rgb: np.ndarray, bbox: tuple[int, int, int, int]) -> None:
        x, y, w, h = (int(v) for v in bbox)
        if w <= 0 or h <= 0:
            return
        x0 = max(0, min(rgb.shape[1] - 1, x))
        y0 = max(0, min(rgb.shape[0] - 1, y))
        x1 = max(0, min(rgb.shape[1] - 1, x + w))
        y1 = max(0, min(rgb.shape[0] - 1, y + h))
        if x1 <= x0 or y1 <= y0:
            return
        color = np.array([0, 255, 0], dtype=np.uint8)
        thickness = 3
        rgb[y0 : y0 + thickness, x0:x1] = color
        rgb[y1 - thickness : y1, x0:x1] = color
        rgb[y0:y1, x0 : x0 + thickness] = color
        rgb[y0:y1, x1 - thickness : x1] = color

    @staticmethod
    def _gui_value(handle: Any | None, default: bool) -> bool:
        if handle is None:
            return bool(default)
        try:
            return bool(handle.value)
        except Exception:
            return bool(default)
