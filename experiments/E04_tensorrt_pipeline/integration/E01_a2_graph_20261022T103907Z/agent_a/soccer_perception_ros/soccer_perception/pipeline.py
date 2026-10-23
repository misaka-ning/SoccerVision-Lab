"""ZED → YOLO → 双目定位 → 跟踪，可选 Viser 可视化。"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np

from soccer_perception.types import BackendConfig
from soccer_perception.core.candidate_selection import StereoCandidateSelector
from soccer_perception.adapters.yolo import BallDetector, YoloBallDetector, parse_int_list
from soccer_perception.core.geometry import StereoTriangulator
from soccer_perception.core.localization import FrameLocalizationContext, StereoTriangulationLocalizer
from soccer_perception.types import FramePacket
from soccer_perception.adapters.zed import FrameSource, ZedFrameSource
from soccer_perception.core.tracking import AlphaBetaBallTracker, BallTracker
from soccer_perception.adapters.viser import ZedRuntimeVisualizer


class SoccerPerceptionPipeline:
    """单路足球感知 pipeline。"""
    def __init__(
        self,
        source: FrameSource,
        detector: BallDetector,
        tracker: BallTracker,
        config: BackendConfig,
        localizer: StereoTriangulationLocalizer | None = None,
        visualizer: ZedRuntimeVisualizer | None = None,
    ):
        # 依赖从外部注入，便于测试时替换 source/detector/tracker 实现。
        self.source = source
        self.detector = detector
        self.tracker = tracker
        self.config = config
        self.localizer = localizer or StereoTriangulationLocalizer()
        self.visualizer = visualizer or ZedRuntimeVisualizer(config)
        self.candidate_selector = StereoCandidateSelector(config)
        self.triangulator: StereoTriangulator | None = None
        self.last_left_det: object | None = None
        self.last_right_det: object | None = None
        self.last_detection_timestamp: float | None = None
        self.last_disparity_px: float | None = None
        self.last_camera_measurement_m: np.ndarray | None = None
        self._prev_wall = 0.0
        self._fps_measured = 0.0
        self._started = False
        self._visualization_frame = None

    def open(self, progress: Callable[[str], None] | None = None) -> None:
        """打开输入源、加载检测器，并准备三角化器。"""

        def report(message: str) -> None:
            if progress is not None:
                progress(message)

        if self.config.disable_cudnn:
            try:
                import torch

                # 某些环境中 cuDNN 初始化会导致模型启动不稳定，默认关闭。
                torch.backends.cudnn.enabled = False
            except ModuleNotFoundError:
                # 无 torch 环境下无需特殊处理。
                pass
        report("soccer_perception_ros opening ZED camera")
        started = time.perf_counter()
        intrinsics = self.source.open()
        report(
            "soccer_perception_ros ZED opened image_size=%s fps=%.1f baseline_m=%.4f elapsed_ms=%.1f"
            % (
                intrinsics.image_size,
                float(intrinsics.fps),
                float(intrinsics.baseline_m),
                (time.perf_counter() - started) * 1000.0,
            )
        )
        report("soccer_perception_ros loading YOLO model %s" % self.config.yolo_model)
        started = time.perf_counter()
        self.detector.load()
        report(
            "soccer_perception_ros YOLO loaded device=%s imgsz=%d elapsed_ms=%.1f"
            % (
                self.config.device or "auto",
                int(self.config.imgsz),
                (time.perf_counter() - started) * 1000.0,
            )
        )
        if self.config.zed_viser_enabled:
            report("soccer_perception_ros opening Viser viewer")
        self.visualizer.open()
        self.triangulator = StereoTriangulator(
            intrinsics,
            max_vertical_delta_px=self.config.max_vertical_delta_px,
            vertical_radius_factor=self.config.vertical_radius_factor,
        )
        self._prev_wall = time.perf_counter()
        self._started = True
        report("soccer_perception_ros pipeline ready")
    def close(self) -> None:
        """释放输入源资源，并标记 pipeline 停止。"""

        try:
            self.source.close()
        finally:
            self.visualizer.close()
            self._started = False
            self._visualization_frame = None

    def next_packet(self) -> FramePacket | None:
        """处理下一帧并生成定位结果；输入结束时返回 None。"""

        if not self._started or self.triangulator is None:
            raise RuntimeError("SoccerPerceptionPipeline.open() must be called before next_packet().")
        frame = self.source.read()
        if frame is None:
            return None

        # 左右目合成一个 YOLO batch，减少每帧两次 predict 的调度开销。
        det_start = time.perf_counter()
        left_candidates, right_candidates = self._detect_stereo_candidates(
            frame.left,
            frame.right,
        )
        global_selection = self.candidate_selector.select(
            left_candidates,
            right_candidates,
            self.triangulator,
            source="global_yolo",
            previous_left=self.last_left_det,
            previous_right=self.last_right_det,
            previous_disparity_px=self.last_disparity_px,
            previous_camera_position_m=self.last_camera_measurement_m,
            previous_timestamp=self.last_detection_timestamp,
            current_timestamp=frame.timestamp,
        )
        left_det = global_selection.left
        right_det = global_selection.right
        det_ms = (time.perf_counter() - det_start) * 1000.0
        selected_source = "global_yolo" if left_det is not None and right_det is not None else "none"
        selected_diagnostics = global_selection.diagnostics

        # Localizer 统一生成本帧 camera FLU 3D measurement;tracker 只消费 position/None。
        localization_context = FrameLocalizationContext(
            left_det=left_det,
            right_det=right_det,
            triangulator=self.triangulator,
            timestamp=frame.timestamp,
            selection_diagnostics=selected_diagnostics or {},
        )
        measurement = self.localizer.localize(localization_context)
        camera_measurement = measurement.position_or_none()
        disparity_px = self.triangulator.disparity_px(left_det, right_det)
        vertical_delta_px = self.triangulator.vertical_delta_px(left_det, right_det)
        if measurement.valid and camera_measurement is not None:
            self.last_camera_measurement_m = camera_measurement.copy()
            self.last_detection_timestamp = float(frame.timestamp)
            if left_det is not None and right_det is not None:
                self.last_left_det = left_det
                self.last_right_det = right_det
                if np.isfinite(disparity_px):
                    self.last_disparity_px = float(disparity_px)

        # camera-frame 3D tracker 在有测量时校正，漏检或 gate 失败时短时预测。
        camera_state = self.tracker.update(camera_measurement, frame.timestamp)
        camera_mode = self._camera_track_mode(camera_state, camera_measurement)
        camera_confidence = self._camera_track_confidence(camera_state)
        loss_age = (float(frame.timestamp) - self.last_detection_timestamp
                    if self.last_detection_timestamp is not None else None)
        tolerated = bool(
            self.config.short_loss_tolerance_enabled
            and camera_measurement is None and camera_state.initialized and camera_state.coasting
            and loss_age is not None and 0 <= loss_age <= self.config.short_loss_tolerance_s
            and np.isfinite(camera_state.p).all()
        )
        # Keep raw measurement validity truthful and expose predictions only
        # during the explicitly bounded short-loss interval.
        usable = camera_state.initialized
        if self.config.short_loss_tolerance_enabled and camera_measurement is None:
            usable = tolerated
            if not usable:
                camera_mode = "LOST"
                camera_confidence = 0.0

        # FPS 使用指数滑动平均，避免前端显示数值大幅抖动。
        now = time.perf_counter()
        inst_fps = 1.0 / max(1e-3, now - self._prev_wall)
        self._fps_measured = 0.85 * self._fps_measured + 0.15 * inst_fps if self._fps_measured else inst_fps
        self._prev_wall = now
        status = camera_mode
        if camera_measurement is not None:
            status = "TRACKED"
        elif not camera_state.initialized:
            status = "LOST"

        candidate_diagnostics = {
            "selected_source": selected_source,
            "selected": selected_source != "none",
            "global": global_selection.diagnostics,
            "selected_pair": selected_diagnostics,
        }
        packet = FramePacket(
            frame_idx=frame.frame_idx,
            timestamp=float(frame.timestamp),
            status=status,
            fps=float(self._fps_measured),
            det_ms=float(det_ms),
            left_det=left_det,
            right_det=right_det,
            ball_3d_measurement=measurement,
            camera_measurement_m=camera_measurement.copy() if camera_measurement is not None else None,
            camera_track_state=camera_state.copy(),
            camera_position_m=camera_state.p.copy() if usable else None,
            camera_velocity_mps=camera_state.v.copy() if usable else None,
            camera_track_mode=camera_mode,
            camera_track_confidence=camera_confidence,
            disparity_px=float(disparity_px),
            vertical_delta_px=float(vertical_delta_px),
            detector_name=self.detector.name,
            baseline_m=float(self.triangulator.intrinsics.baseline_m),
            camera_intrinsics=self._camera_intrinsics_diagnostics(),
            candidate_diagnostics=candidate_diagnostics,
            short_loss_tolerated=tolerated,
            short_loss_age_s=loss_age if camera_measurement is None else 0.0,
            short_loss_timeout_s=self.config.short_loss_tolerance_s,
        )
        self._visualization_frame = frame
        return packet

    def update_visualization(self, packet: FramePacket) -> None:
        """Refresh Viser once per ROS output, before the next SDK grab."""
        if self._visualization_frame is not None:
            self.visualizer.update(self._visualization_frame, packet)

    def _detect_stereo_candidates(
        self,
        left_frame: np.ndarray,
        right_frame: np.ndarray,
    ) -> tuple[list, list]:
        batch_detect = getattr(self.detector, "detect_candidates_batch", None)
        if callable(batch_detect):
            left_candidates, right_candidates = batch_detect(
                [left_frame, right_frame],
                top_k=self.config.yolo_top_k,
            )
            return left_candidates, right_candidates
        return (
            self.detector.detect_candidates(left_frame, top_k=self.config.yolo_top_k),
            self.detector.detect_candidates(right_frame, top_k=self.config.yolo_top_k),
        )
    def _camera_intrinsics_diagnostics(self) -> dict[str, object]:
        if self.triangulator is None:
            return {}
        k = self.triangulator.intrinsics.K
        fx = float(k[0, 0])
        fy = float(k[1, 1])
        cx = float(k[0, 2])
        cy = float(k[1, 2])
        baseline_m = float(self.triangulator.intrinsics.baseline_m)
        width, height = self.triangulator.intrinsics.image_size
        return {
            "fx_px": fx,
            "fy_px": fy,
            "cx_px": cx,
            "cy_px": cy,
            "baseline_m": baseline_m,
            "fx_baseline_m_px": fx * baseline_m,
            "image_size_wh": [int(width), int(height)],
            "fps": float(self.triangulator.intrinsics.fps),
        }

    def _camera_track_mode(self, state, measurement: np.ndarray | None) -> str:
        if measurement is not None and state.initialized:
            return "TRACKED"
        if state.initialized and state.coasting:
            return "OCCLUDED_PREDICT"
        return "LOST"
    def _camera_track_confidence(self, state) -> float:
        if not state.initialized:
            return 0.0
        if not state.coasting:
            return 1.0
        ratio = min(1.0, state.frames_since_measurement / max(1, self.config.max_coast_frames))
        return float(max(0.15, 1.0 - 0.75 * ratio))


class PipelineFactory:
    """根据 BackendConfig 创建完整 pipeline 的工厂。"""
    def __init__(self, config: BackendConfig):
        self.config = config
    def create(self) -> SoccerPerceptionPipeline:
        """创建供 ROS 节点使用的感知流程。"""

        return SoccerPerceptionPipeline(
            source=self._create_source(),
            detector=self._create_detector(),
            tracker=AlphaBetaBallTracker(
                max_coast_frames=self.config.max_coast_frames,
                max_coast_time_s=self.config.max_coast_time_s,
                velocity_decay=self.config.velocity_decay,
            ),
            config=self.config,
        )
    def _create_source(self) -> FrameSource:
        """创建 ZED 输入源。"""

        return ZedFrameSource(self.config)
    def _create_detector(self) -> BallDetector:
        """创建 YOLO 检测器。"""

        return YoloBallDetector(
            model_path=self.config.yolo_model,
            conf=self.config.det_conf,
            imgsz=self.config.imgsz,
            device=self.config.device,
            class_ids=parse_int_list(self.config.yolo_class_ids),
            half=self.config.half,
            tensorrt=self.config.yolo_tensorrt,
            engine_path=self.config.yolo_engine_path,
            trt_batch=self.config.yolo_trt_batch,
            trt_dynamic=self.config.yolo_trt_dynamic,
            trt_workspace_gb=self.config.yolo_trt_workspace_gb,
        )
