"""Camera-frame 3D ball localization sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from soccer_perception.core.geometry import StereoTriangulator
from soccer_perception.types import Ball3DMeasurement, BallDetection


MEASUREMENT_SOURCE_STEREO = "stereo_triangulation"

CAMERA_FLU_DIAGNOSTICS: dict[str, Any] = {
    "coordinate_frame": "camera_flu",
    "axes": {
        "x_m": "forward",
        "y_m": "left",
        "z_m": "up",
    },
}


@dataclass
class FrameLocalizationContext:
    """Inputs needed by a localizer for one frame."""

    left_det: BallDetection | None
    right_det: BallDetection | None
    triangulator: StereoTriangulator
    timestamp: float
    selection_diagnostics: dict[str, Any] = field(default_factory=dict)


class StereoTriangulationLocalizer:
    """Build a camera FLU 3D measurement from the selected stereo pair."""

    source_name = MEASUREMENT_SOURCE_STEREO

    def localize(self, context: FrameLocalizationContext) -> Ball3DMeasurement:
        left = context.left_det
        right = context.right_det
        triangulator = context.triangulator
        selection_diagnostics = dict(context.selection_diagnostics or {})

        disparity_px = triangulator.disparity_px(left, right)
        vertical_delta_px = triangulator.vertical_delta_px(left, right)
        has_stereo_detections = left is not None and right is not None
        vertical_match = bool(has_stereo_detections and triangulator.is_vertical_match(left, right))
        quality = _selected_quality(selection_diagnostics)
        diagnostics = self._base_diagnostics(
            timestamp=context.timestamp,
            has_stereo_detections=has_stereo_detections,
            disparity_px=disparity_px,
            vertical_delta_px=vertical_delta_px,
            vertical_match=vertical_match,
            selection_diagnostics=selection_diagnostics,
        )

        if not has_stereo_detections:
            return Ball3DMeasurement.invalid(
                source=self.source_name,
                reject_reasons=["missing_stereo_pair"],
                diagnostics=diagnostics,
                quality=quality,
            )
        if not np.isfinite(disparity_px) or disparity_px <= 0.5:
            return Ball3DMeasurement.invalid(
                source=self.source_name,
                reject_reasons=["bad_disparity"],
                diagnostics=diagnostics,
                quality=quality,
            )
        if not vertical_match:
            return Ball3DMeasurement.invalid(
                source=self.source_name,
                reject_reasons=["vertical_mismatch"],
                diagnostics=diagnostics,
                quality=quality,
            )

        position = triangulator.triangulate_camera(left, right)
        if position is None:
            return Ball3DMeasurement.invalid(
                source=self.source_name,
                reject_reasons=["triangulation_failed"],
                diagnostics=diagnostics,
                quality=quality,
            )

        position = _finite_vec3_or_none(position)
        if position is None:
            return Ball3DMeasurement.invalid(
                source=self.source_name,
                reject_reasons=["triangulation_non_finite"],
                diagnostics=diagnostics,
                quality=quality,
            )

        diagnostics["position_camera_m"] = {
            "x_front": float(position[0]),
            "y_left": float(position[1]),
            "z_up": float(position[2]),
        }
        return Ball3DMeasurement.valid_measurement(
            position,
            source=self.source_name,
            confidence=1.0,
            quality=quality,
            diagnostics=diagnostics,
        )

    def _base_diagnostics(
        self,
        *,
        timestamp: float,
        has_stereo_detections: bool,
        disparity_px: float,
        vertical_delta_px: float,
        vertical_match: bool,
        selection_diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        selected_pair_metrics = selection_diagnostics.get("selected_pair_metrics")
        if selected_pair_metrics is None:
            selected_pair_metrics = selection_diagnostics.get("best")
        return {
            **CAMERA_FLU_DIAGNOSTICS,
            "timestamp": float(timestamp),
            "has_stereo_detections": bool(has_stereo_detections),
            "disparity_px": _finite_float_or_none(disparity_px),
            "vertical_delta_px": _finite_float_or_none(vertical_delta_px),
            "vertical_match": bool(vertical_match),
            "selected_score": _finite_float_or_none(selection_diagnostics.get("selected_score")),
            "selected_pair_metrics": selected_pair_metrics,
            "selector_reject_reasons": selection_diagnostics.get("reject_reasons", {}),
        }


def _finite_vec3_or_none(value: np.ndarray) -> np.ndarray | None:
    vector = np.asarray(value, dtype=np.float64).reshape(-1)
    if vector.size < 3 or not np.all(np.isfinite(vector[:3])):
        return None
    return vector[:3].copy()

def _finite_float_or_none(value: object) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(converted):
        return None
    return converted

def _selected_quality(selection_diagnostics: dict[str, Any]) -> float:
    selected_score = _finite_float_or_none(selection_diagnostics.get("selected_score"))
    return 0.0 if selected_score is None else selected_score
