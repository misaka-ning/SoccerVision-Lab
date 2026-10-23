"""用于低置信度检测召回的双目候选选择。

检测器可能在左右目图像中分别返回多个低置信度候选。本模块使用极线几何和
可选的轨迹预测选择最可信的双目配对，而不是只相信单张图像中置信度最高的结果。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np

from soccer_perception.types import BackendConfig
from soccer_perception.core.geometry import StereoTriangulator
from soccer_perception.types import BallDetection


@dataclass
class CandidateSelectionResult:
    """选中的双目配对及诊断信息。"""

    left: BallDetection | None
    right: BallDetection | None
    diagnostics: dict[str, Any]


@dataclass
class CandidateGateResult:
    """单目候选门控输出。"""

    candidates: list[BallDetection]
    reject_reasons: Counter[str]


class StereoCandidateSelector:
    """使用双目几何和质量门控对左右候选配对打分。"""

    def __init__(self, config: BackendConfig):
        self.config = config

    def select(
        self,
        left_candidates: list[BallDetection],
        right_candidates: list[BallDetection],
        triangulator: StereoTriangulator,
        *,
        source: str,
        previous_left: BallDetection | None = None,
        previous_right: BallDetection | None = None,
        previous_disparity_px: float | None = None,
        previous_camera_position_m: np.ndarray | None = None,
        previous_timestamp: float | None = None,
        current_timestamp: float | None = None,
    ) -> CandidateSelectionResult:
        image_size = self._image_size_wh(triangulator)
        left_gate = self._filter_mono_candidates(left_candidates, image_size)
        right_gate = self._filter_mono_candidates(right_candidates, image_size)

        pair_reject_reasons: Counter[str] = Counter()
        best_pair: tuple[BallDetection, BallDetection] | None = None
        best_score: float | None = None
        best_metrics: dict[str, Any] = {}
        best_rejected_metrics: dict[str, Any] = {}
        best_rejected_rank: float | None = None
        pair_count_before = 0
        pair_count_after = 0

        for left in left_gate.candidates:
            for right in right_gate.candidates:
                pair_count_before += 1
                accepted, reason, metrics = self._score_pair(
                    left,
                    right,
                    triangulator,
                    previous_left=previous_left,
                    previous_right=previous_right,
                    previous_disparity_px=previous_disparity_px,
                    previous_camera_position_m=previous_camera_position_m,
                    previous_timestamp=previous_timestamp,
                    current_timestamp=current_timestamp,
                )
                if not accepted:
                    pair_reject_reasons[reason] += 1
                    rejected_rank = self._rejected_rank(metrics)
                    if best_rejected_rank is None or rejected_rank > best_rejected_rank:
                        best_rejected_rank = rejected_rank
                        best_rejected_metrics = dict(metrics)
                        best_rejected_metrics["reject_reason"] = reason
                    continue
                pair_count_after += 1
                score = float(metrics["score"])
                if best_score is None or score > best_score:
                    best_score = score
                    best_pair = (left, right)
                    best_metrics = metrics

        monocular_reject_reasons = Counter(left_gate.reject_reasons)
        monocular_reject_reasons.update(right_gate.reject_reasons)
        diagnostics: dict[str, Any] = {
            "source": source,
            "left_count": len(left_candidates),
            "right_count": len(right_candidates),
            "left_count_before": len(left_candidates),
            "right_count_before": len(right_candidates),
            "left_count_after": len(left_gate.candidates),
            "right_count_after": len(right_gate.candidates),
            "pair_count": pair_count_before,
            "pair_count_before": pair_count_before,
            "pair_count_after": pair_count_after,
            "selected": best_pair is not None,
            "selected_score": best_score,
            "selected_source": source if best_pair is not None else None,
            "monocular_reject_reasons": dict(monocular_reject_reasons),
            "left_monocular_reject_reasons": dict(left_gate.reject_reasons),
            "right_monocular_reject_reasons": dict(right_gate.reject_reasons),
            "pair_reject_reasons": dict(pair_reject_reasons),
            "reject_reasons": dict(pair_reject_reasons),
            "best": best_metrics,
            "selected_pair_metrics": best_metrics,
            "best_rejected_metrics": best_rejected_metrics,
            "gate_config": {
                "candidate_bbox_gate_enabled": bool(self.config.candidate_bbox_gate_enabled),
                "candidate_score_gate_enabled": bool(self.config.candidate_score_gate_enabled),
                "candidate_radius_consistency_enabled": bool(self.config.candidate_radius_consistency_enabled),
                "candidate_radius_consistency_hard_gate": bool(self.config.candidate_radius_consistency_hard_gate),
            },
        }
        if best_pair is None:
            return CandidateSelectionResult(None, None, diagnostics)
        return CandidateSelectionResult(best_pair[0], best_pair[1], diagnostics)

    def _score_pair(
        self,
        left: BallDetection,
        right: BallDetection,
        triangulator: StereoTriangulator,
        *,
        previous_left: BallDetection | None,
        previous_right: BallDetection | None,
        previous_disparity_px: float | None,
        previous_camera_position_m: np.ndarray | None,
        previous_timestamp: float | None,
        current_timestamp: float | None,
    ) -> tuple[bool, str, dict[str, Any]]:
        avg_detector_score = 0.5 * (float(left.score) + float(right.score))
        disparity_px = triangulator.disparity_px(left, right)
        if not np.isfinite(disparity_px) or disparity_px <= 0.5:
            return False, "bad_disparity", {
                "avg_detector_score": float(avg_detector_score),
                "left_score": float(left.score),
                "right_score": float(right.score),
                "disparity_px": float(disparity_px),
                "left_source": left.source,
                "right_source": right.source,
            }

        vertical_delta_px = triangulator.vertical_delta_px(left, right)
        vertical_limit_px = max(
            float(triangulator.max_vertical_delta_px),
            float(triangulator.vertical_radius_factor) * max(float(left.radius_px), float(right.radius_px)),
        )
        if not np.isfinite(vertical_delta_px) or vertical_delta_px >= vertical_limit_px:
            return False, "vertical_mismatch", {
                "avg_detector_score": float(avg_detector_score),
                "left_score": float(left.score),
                "right_score": float(right.score),
                "disparity_px": float(disparity_px),
                "vertical_delta_px": float(vertical_delta_px),
                "vertical_limit_px": float(vertical_limit_px),
                "left_source": left.source,
                "right_source": right.source,
            }

        radius_min = max(1e-3, min(float(left.radius_px), float(right.radius_px)))
        radius_ratio = max(float(left.radius_px), float(right.radius_px)) / radius_min
        if radius_ratio > float(self.config.candidate_max_radius_ratio):
            return False, "radius_mismatch", {
                "avg_detector_score": float(avg_detector_score),
                "left_score": float(left.score),
                "right_score": float(right.score),
                "disparity_px": float(disparity_px),
                "vertical_delta_px": float(vertical_delta_px),
                "vertical_limit_px": float(vertical_limit_px),
                "radius_ratio": float(radius_ratio),
                "left_source": left.source,
                "right_source": right.source,
            }

        bbox_size_ratio = self._bbox_pair_size_ratio(left, right)
        if (
            self.config.candidate_bbox_gate_enabled
            and bbox_size_ratio is not None
            and bbox_size_ratio > float(self.config.candidate_bbox_pair_max_size_ratio)
        ):
            return False, "bbox_pair_size_mismatch", {
                "avg_detector_score": float(avg_detector_score),
                "left_score": float(left.score),
                "right_score": float(right.score),
                "disparity_px": float(disparity_px),
                "vertical_delta_px": float(vertical_delta_px),
                "vertical_limit_px": float(vertical_limit_px),
                "radius_ratio": float(radius_ratio),
                "bbox_size_ratio": float(bbox_size_ratio),
                "left_source": left.source,
                "right_source": right.source,
            }

        camera_position_m = triangulator.triangulate_camera(left, right)
        if camera_position_m is None:
            return False, "triangulation_failed", {
                "avg_detector_score": float(avg_detector_score),
                "left_score": float(left.score),
                "right_score": float(right.score),
                "disparity_px": float(disparity_px),
                "vertical_delta_px": float(vertical_delta_px),
                "vertical_limit_px": float(vertical_limit_px),
                "radius_ratio": float(radius_ratio),
                "bbox_size_ratio": bbox_size_ratio,
                "left_source": left.source,
                "right_source": right.source,
            }
        camera_position_m = np.asarray(camera_position_m, dtype=np.float64).reshape(-1)
        if camera_position_m.size < 3 or not np.all(np.isfinite(camera_position_m[:3])):
            return False, "triangulation_non_finite", {
                "avg_detector_score": float(avg_detector_score),
                "left_score": float(left.score),
                "right_score": float(right.score),
                "disparity_px": float(disparity_px),
                "vertical_delta_px": float(vertical_delta_px),
                "vertical_limit_px": float(vertical_limit_px),
                "radius_ratio": float(radius_ratio),
                "bbox_size_ratio": bbox_size_ratio,
                "camera_position_m": self._vec3_or_none(camera_position_m),
                "left_source": left.source,
                "right_source": right.source,
            }

        depth_m = float(camera_position_m[0])
        if depth_m < float(self.config.candidate_min_depth_m):
            return False, "depth_too_near", {
                "avg_detector_score": float(avg_detector_score),
                "left_score": float(left.score),
                "right_score": float(right.score),
                "disparity_px": float(disparity_px),
                "vertical_delta_px": float(vertical_delta_px),
                "vertical_limit_px": float(vertical_limit_px),
                "radius_ratio": float(radius_ratio),
                "bbox_size_ratio": bbox_size_ratio,
                "camera_position_m": self._vec3_or_none(camera_position_m),
                "depth_m": depth_m,
                "min_depth_m": float(self.config.candidate_min_depth_m),
                "left_source": left.source,
                "right_source": right.source,
            }
        if depth_m > float(self.config.candidate_max_depth_m):
            return False, "depth_too_far", {
                "avg_detector_score": float(avg_detector_score),
                "left_score": float(left.score),
                "right_score": float(right.score),
                "disparity_px": float(disparity_px),
                "vertical_delta_px": float(vertical_delta_px),
                "vertical_limit_px": float(vertical_limit_px),
                "radius_ratio": float(radius_ratio),
                "bbox_size_ratio": bbox_size_ratio,
                "camera_position_m": self._vec3_or_none(camera_position_m),
                "depth_m": depth_m,
                "max_depth_m": float(self.config.candidate_max_depth_m),
                "left_source": left.source,
                "right_source": right.source,
            }

        prediction_3d_distance_m = None
        speed_mps = None
        if previous_camera_position_m is not None:
            previous = np.asarray(previous_camera_position_m, dtype=np.float64).reshape(-1)
            if previous.size >= 3 and np.all(np.isfinite(previous[:3])):
                prediction_3d_distance_m = float(np.linalg.norm(camera_position_m[:3] - previous[:3]))
                if (
                    self.config.candidate_max_3d_jump_m is not None
                    and prediction_3d_distance_m > float(self.config.candidate_max_3d_jump_m)
                ):
                    return False, "camera_3d_jump_too_large", {
                        "avg_detector_score": float(avg_detector_score),
                        "left_score": float(left.score),
                        "right_score": float(right.score),
                        "disparity_px": float(disparity_px),
                        "vertical_delta_px": float(vertical_delta_px),
                        "vertical_limit_px": float(vertical_limit_px),
                        "radius_ratio": float(radius_ratio),
                        "bbox_size_ratio": bbox_size_ratio,
                        "camera_position_m": self._vec3_or_none(camera_position_m),
                        "prediction_3d_distance_m": prediction_3d_distance_m,
                        "max_3d_jump_m": float(self.config.candidate_max_3d_jump_m),
                        "left_source": left.source,
                        "right_source": right.source,
                    }
                if previous_timestamp is not None and current_timestamp is not None:
                    dt_s = float(current_timestamp) - float(previous_timestamp)
                    if np.isfinite(dt_s) and dt_s > 1e-6:
                        speed_mps = prediction_3d_distance_m / dt_s
                        if (
                            self.config.candidate_max_speed_mps is not None
                            and speed_mps > float(self.config.candidate_max_speed_mps)
                        ):
                            return False, "camera_speed_too_large", {
                                "avg_detector_score": float(avg_detector_score),
                                "left_score": float(left.score),
                                "right_score": float(right.score),
                                "disparity_px": float(disparity_px),
                                "vertical_delta_px": float(vertical_delta_px),
                                "vertical_limit_px": float(vertical_limit_px),
                                "radius_ratio": float(radius_ratio),
                                "bbox_size_ratio": bbox_size_ratio,
                                "camera_position_m": self._vec3_or_none(camera_position_m),
                                "prediction_3d_distance_m": prediction_3d_distance_m,
                                "speed_mps": float(speed_mps),
                                "max_speed_mps": float(self.config.candidate_max_speed_mps),
                                "dt_s": float(dt_s),
                                "left_source": left.source,
                                "right_source": right.source,
                            }

        score = float(self.config.candidate_yolo_score_weight) * avg_detector_score
        score -= float(self.config.candidate_vertical_penalty) * (vertical_delta_px / max(1.0, vertical_limit_px))

        prediction_distance_px = None
        if previous_left is not None and previous_right is not None:
            left_dist = float(np.linalg.norm(np.asarray(left.center) - np.asarray(previous_left.center)))
            right_dist = float(np.linalg.norm(np.asarray(right.center) - np.asarray(previous_right.center)))
            prediction_distance_px = 0.5 * (left_dist + right_dist)
            score -= float(self.config.candidate_prediction_penalty) * prediction_distance_px

        disparity_jump_px = None
        if previous_disparity_px is not None and np.isfinite(previous_disparity_px):
            disparity_jump_px = abs(float(disparity_px) - float(previous_disparity_px))
            score -= float(self.config.candidate_disparity_jump_penalty) * disparity_jump_px

        if prediction_3d_distance_m is not None:
            score -= float(self.config.candidate_prediction_3d_penalty) * prediction_3d_distance_m

        radius_consistency = self._radius_consistency_metrics(left, right, triangulator, depth_m)
        radius_consistency_ratio = radius_consistency.get("radius_consistency_ratio")
        radius_consistency_excess = radius_consistency.get("radius_consistency_excess")
        if (
            self.config.candidate_radius_consistency_enabled
            and self.config.candidate_radius_consistency_hard_gate
            and radius_consistency_excess is not None
            and radius_consistency_excess > 0.0
        ):
            metrics = {
                "avg_detector_score": float(avg_detector_score),
                "left_score": float(left.score),
                "right_score": float(right.score),
                "vertical_delta_px": float(vertical_delta_px),
                "vertical_limit_px": float(vertical_limit_px),
                "disparity_px": float(disparity_px),
                "radius_ratio": float(radius_ratio),
                "bbox_size_ratio": bbox_size_ratio,
                "camera_position_m": self._vec3_or_none(camera_position_m),
                "depth_m": depth_m,
                "prediction_distance_px": prediction_distance_px,
                "disparity_jump_px": disparity_jump_px,
                "prediction_3d_distance_m": prediction_3d_distance_m,
                "speed_mps": speed_mps,
                "left_source": left.source,
                "right_source": right.source,
            }
            metrics.update(radius_consistency)
            return False, "radius_consistency_mismatch", metrics

        if (
            self.config.candidate_radius_consistency_enabled
            and radius_consistency_excess is not None
            and radius_consistency_excess > 0.0
        ):
            score -= float(radius_consistency_excess)

        return True, "ok", {
            "score": float(score),
            "avg_detector_score": float(avg_detector_score),
            "left_score": float(left.score),
            "right_score": float(right.score),
            "vertical_delta_px": float(vertical_delta_px),
            "vertical_limit_px": float(vertical_limit_px),
            "disparity_px": float(disparity_px),
            "radius_ratio": float(radius_ratio),
            "bbox_size_ratio": bbox_size_ratio,
            "camera_position_m": self._vec3_or_none(camera_position_m),
            "depth_m": depth_m,
            "prediction_distance_px": prediction_distance_px,
            "disparity_jump_px": disparity_jump_px,
            "prediction_3d_distance_m": prediction_3d_distance_m,
            "speed_mps": speed_mps,
            "radius_consistency_ratio": radius_consistency_ratio,
            "radius_consistency_excess": radius_consistency_excess,
            "expected_radius_px": radius_consistency.get("expected_radius_px"),
            "observed_radius_px": radius_consistency.get("observed_radius_px"),
            "left_source": left.source,
            "right_source": right.source,
        }

    def _filter_mono_candidates(
        self,
        candidates: list[BallDetection],
        image_size: tuple[int, int],
    ) -> CandidateGateResult:
        reject_reasons: Counter[str] = Counter()
        filtered: list[BallDetection] = []
        for candidate in candidates:
            reason = self._mono_reject_reason(candidate, image_size)
            if reason is None:
                filtered.append(candidate)
                continue
            reject_reasons[reason] += 1
        return CandidateGateResult(candidates=filtered, reject_reasons=reject_reasons)

    def _mono_reject_reason(self, candidate: BallDetection, image_size: tuple[int, int]) -> str | None:
        if self.config.candidate_score_gate_enabled and self._score_below_threshold(candidate):
            return "score_below_threshold"

        if self.config.candidate_min_radius_px is not None or self.config.candidate_max_radius_px is not None:
            radius = float(candidate.radius_px)
            if not np.isfinite(radius):
                return "radius_non_finite"
            if self.config.candidate_min_radius_px is not None and radius < float(self.config.candidate_min_radius_px):
                return "radius_too_small"
            if self.config.candidate_max_radius_px is not None and radius > float(self.config.candidate_max_radius_px):
                return "radius_too_large"

        if not self.config.candidate_bbox_gate_enabled:
            return None

        width, height = image_size
        bbox = np.asarray(candidate.bbox, dtype=np.float64).reshape(-1)
        if bbox.size < 4 or not np.all(np.isfinite(bbox[:4])):
            return "bbox_non_finite"
        x, y, w, h = [float(v) for v in bbox[:4]]
        if w <= 0.0 or h <= 0.0:
            return "bbox_invalid_size"
        if x + w <= 0.0 or y + h <= 0.0 or x >= width or y >= height:
            return "bbox_outside_image"

        eff_x1, eff_y1 = x, y
        eff_x2, eff_y2 = x + w, y + h
        if self.config.candidate_bbox_clip_to_image:
            eff_x1 = max(0.0, min(float(width), eff_x1))
            eff_y1 = max(0.0, min(float(height), eff_y1))
            eff_x2 = max(0.0, min(float(width), eff_x2))
            eff_y2 = max(0.0, min(float(height), eff_y2))
        eff_w = max(0.0, eff_x2 - eff_x1)
        eff_h = max(0.0, eff_y2 - eff_y1)
        if eff_w <= 0.0 or eff_h <= 0.0:
            return "bbox_outside_image"
        area_px = eff_w * eff_h
        if area_px < float(self.config.candidate_bbox_min_area_px):
            return "bbox_too_small"
        image_area = max(1.0, float(width * height))
        if area_px / image_area > float(self.config.candidate_bbox_max_area_ratio):
            return "bbox_too_large"
        aspect_ratio = eff_w / max(1e-6, eff_h)
        if (
            aspect_ratio < float(self.config.candidate_bbox_min_aspect_ratio)
            or aspect_ratio > float(self.config.candidate_bbox_max_aspect_ratio)
        ):
            return "bbox_bad_aspect_ratio"

        radius = float(candidate.radius_px)
        if not np.isfinite(radius):
            return "radius_non_finite"
        if self.config.candidate_min_radius_px is not None and radius < float(self.config.candidate_min_radius_px):
            return "radius_too_small"
        if self.config.candidate_max_radius_px is not None and radius > float(self.config.candidate_max_radius_px):
            return "radius_too_large"
        return None

    def _score_below_threshold(self, candidate: BallDetection) -> bool:
        min_score = self.config.candidate_min_yolo_score
        if min_score is None:
            return False
        if not self._is_confidence_detector(candidate):
            return False
        score = float(candidate.score)
        return (not np.isfinite(score)) or score < float(min_score)

    def _is_confidence_detector(self, candidate: BallDetection) -> bool:
        source = str(candidate.source).lower()
        return source.startswith("yolo")

    def _bbox_pair_size_ratio(self, left: BallDetection, right: BallDetection) -> float | None:
        try:
            _, _, left_w, left_h = [float(v) for v in left.bbox]
            _, _, right_w, right_h = [float(v) for v in right.bbox]
        except (TypeError, ValueError):
            return None
        if min(left_w, left_h, right_w, right_h) <= 0.0:
            return None
        width_ratio = max(left_w, right_w) / max(1e-6, min(left_w, right_w))
        height_ratio = max(left_h, right_h) / max(1e-6, min(left_h, right_h))
        return float(max(width_ratio, height_ratio))

    def _radius_consistency_metrics(
        self,
        left: BallDetection,
        right: BallDetection,
        triangulator: StereoTriangulator,
        depth_m: float,
    ) -> dict[str, float | None]:
        if not self.config.candidate_radius_consistency_enabled:
            return {
                "expected_radius_px": None,
                "observed_radius_px": None,
                "radius_consistency_ratio": None,
                "radius_consistency_excess": None,
            }
        fx = float(triangulator.intrinsics.K[0, 0])
        ball_radius_m = float(self.config.candidate_expected_ball_radius_m)
        if not np.isfinite(fx) or not np.isfinite(depth_m) or depth_m <= 1e-6 or ball_radius_m <= 0.0:
            return {
                "expected_radius_px": None,
                "observed_radius_px": None,
                "radius_consistency_ratio": None,
                "radius_consistency_excess": None,
            }
        expected_radius_px = fx * ball_radius_m / depth_m
        observed_radius_px = 0.5 * (float(left.radius_px) + float(right.radius_px))
        if expected_radius_px <= 1e-6 or not np.isfinite(observed_radius_px):
            ratio = None
            excess = None
        else:
            ratio = observed_radius_px / expected_radius_px
            tolerance = max(0.0, float(self.config.candidate_radius_consistency_tolerance_ratio))
            excess = max(0.0, abs(float(ratio) - 1.0) - tolerance)
        return {
            "expected_radius_px": float(expected_radius_px),
            "observed_radius_px": float(observed_radius_px),
            "radius_consistency_ratio": None if ratio is None else float(ratio),
            "radius_consistency_excess": None if excess is None else float(excess),
        }

    def _image_size_wh(self, triangulator: StereoTriangulator) -> tuple[int, int]:
        # 所有帧源都会将 CameraIntrinsics.image_size 填充为 (width, height)。
        width, height = triangulator.intrinsics.image_size
        return max(1, int(width)), max(1, int(height))

    def _vec3_or_none(self, value: np.ndarray | None) -> list[float] | None:
        if value is None:
            return None
        arr = np.asarray(value, dtype=np.float64).reshape(-1)
        if arr.size < 3:
            return None
        return [float(v) for v in arr[:3]]

    def _rejected_rank(self, metrics: dict[str, Any]) -> float:
        if "avg_detector_score" in metrics:
            try:
                score = float(metrics["avg_detector_score"])
                return score if np.isfinite(score) else float("-inf")
            except (TypeError, ValueError):
                return float("-inf")
        return float("-inf")
