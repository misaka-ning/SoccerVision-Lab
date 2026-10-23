from __future__ import annotations

import json
import unittest

import numpy as np

from soccer_perception.ros.output import (
    build_ball_camera_diagnostics,
    build_ball_position_camera_payload,
)
from soccer_perception.core.geometry import StereoTriangulator
from soccer_perception.core.localization import (
    MEASUREMENT_SOURCE_STEREO,
    FrameLocalizationContext,
    StereoTriangulationLocalizer,
)
from soccer_perception.types import (
    Ball3DMeasurement,
    BallDetection,
    CameraIntrinsics,
    FramePacket,
    TrackState,
)


def _det(
    u: float,
    v: float,
    *,
    radius: float = 20.0,
    score: float = 0.8,
) -> BallDetection:
    return BallDetection(
        center=np.array([u, v], dtype=np.float64),
        radius_px=radius,
        score=score,
        bbox=(int(round(u - radius)), int(round(v - radius)), int(round(radius * 2.0)), int(round(radius * 2.0))),
        source="yolo",
    )


def _triangulator() -> StereoTriangulator:
    return StereoTriangulator(
        CameraIntrinsics(
            K=np.array(
                [
                    [600.0, 0.0, 320.0],
                    [0.0, 600.0, 240.0],
                    [0.0, 0.0, 1.0],
                ],
                dtype=np.float64,
            ),
            baseline_m=0.12,
            fps=60.0,
            image_size=(640, 480),
        ),
        max_vertical_delta_px=12.0,
        vertical_radius_factor=0.5,
    )


class NonFiniteTriangulator(StereoTriangulator):
    def triangulate_camera(self, left_det: BallDetection, right_det: BallDetection) -> np.ndarray | None:
        return np.array([1.0, np.nan, 2.0], dtype=np.float64)


def _localize(
    left: BallDetection | None,
    right: BallDetection | None,
    triangulator: StereoTriangulator | None = None,
) -> Ball3DMeasurement:
    return StereoTriangulationLocalizer().localize(
        FrameLocalizationContext(
            left_det=left,
            right_det=right,
            triangulator=triangulator or _triangulator(),
            timestamp=1.25,
            selection_diagnostics={
                "selected_score": 0.82,
                "selected_pair_metrics": {"score": 0.82},
                "reject_reasons": {},
            },
        )
    )


def _packet(measurement: Ball3DMeasurement) -> FramePacket:
    position = measurement.position_or_none()
    initialized = position is not None
    track_state = TrackState(
        p=position.copy() if position is not None else np.zeros(3, dtype=np.float64),
        v=np.zeros(3, dtype=np.float64),
        last_t=1.25,
        initialized=initialized,
    )
    return FramePacket(
        frame_idx=7,
        timestamp=1.25,
        status="TRACKED" if initialized else "LOST",
        fps=30.0,
        det_ms=4.0,
        left_det=None,
        right_det=None,
        ball_3d_measurement=measurement,
        camera_measurement_m=position.copy() if position is not None else None,
        camera_track_state=track_state,
        camera_position_m=position.copy() if initialized else None,
        camera_velocity_mps=np.zeros(3, dtype=np.float64) if initialized else None,
        camera_track_mode="TRACKED" if initialized else "LOST",
        camera_track_confidence=1.0 if initialized else 0.0,
        disparity_px=float(measurement.diagnostics.get("disparity_px") or 0.0),
        vertical_delta_px=float(measurement.diagnostics.get("vertical_delta_px") or 0.0),
        detector_name="test",
        baseline_m=0.12,
    )


class MeasurementLocalizationTest(unittest.TestCase):
    def test_valid_stereo_measurement(self) -> None:
        measurement = _localize(_det(320, 240), _det(280, 240))

        self.assertTrue(measurement.valid)
        self.assertEqual(measurement.source, MEASUREMENT_SOURCE_STEREO)
        self.assertEqual(measurement.reject_reasons, [])
        self.assertAlmostEqual(float(measurement.position_camera_m[0]), 1.8)
        self.assertEqual(measurement.confidence, 1.0)
        self.assertEqual(measurement.quality, 0.82)
        self.assertEqual(measurement.diagnostics["coordinate_frame"], "camera_flu")

    def test_missing_pair_is_invalid_measurement(self) -> None:
        measurement = _localize(_det(320, 240), None)

        self.assertFalse(measurement.valid)
        self.assertEqual(measurement.source, MEASUREMENT_SOURCE_STEREO)
        self.assertEqual(measurement.reject_reasons, ["missing_stereo_pair"])
        self.assertIsNone(measurement.position_or_none())

    def test_bad_disparity_is_invalid_measurement(self) -> None:
        measurement = _localize(_det(250, 240), _det(280, 240))

        self.assertFalse(measurement.valid)
        self.assertEqual(measurement.reject_reasons, ["bad_disparity"])

    def test_vertical_mismatch_is_invalid_measurement(self) -> None:
        measurement = _localize(_det(320, 240), _det(280, 270))

        self.assertFalse(measurement.valid)
        self.assertEqual(measurement.reject_reasons, ["vertical_mismatch"])

    def test_non_finite_triangulation_is_invalid_measurement(self) -> None:
        measurement = _localize(_det(320, 240), _det(280, 240), NonFiniteTriangulator(_triangulator().intrinsics))

        self.assertFalse(measurement.valid)
        self.assertEqual(measurement.reject_reasons, ["triangulation_non_finite"])

    def test_measurement_to_dict_is_json_safe(self) -> None:
        measurement = Ball3DMeasurement.invalid(
            source=MEASUREMENT_SOURCE_STEREO,
            reject_reasons=["test"],
            diagnostics={
                "bad_float": float("nan"),
                "array": np.array([1.0, np.inf], dtype=np.float64),
                "np_float": np.float64(2.5),
            },
            quality=float("nan"),
        )

        encoded = json.dumps(measurement.to_dict(), allow_nan=False)
        decoded = json.loads(encoded)
        self.assertIsNone(decoded["diagnostics"]["bad_float"])
        self.assertEqual(decoded["diagnostics"]["array"], [1.0, None])
        self.assertEqual(decoded["diagnostics"]["np_float"], 2.5)
        self.assertEqual(decoded["quality"], 0.0)

    def test_camera_payload_stays_seven_fields(self) -> None:
        measurement = Ball3DMeasurement.valid_measurement(
            np.array([2.50, -0.25, 0.10], dtype=np.float64),
            source=MEASUREMENT_SOURCE_STEREO,
        )
        packet = _packet(measurement)
        payload = build_ball_position_camera_payload(packet)

        self.assertEqual(set(payload), {"type", "timestamp", "valid", "confidence", "x_m", "y_m", "z_m"})
        self.assertTrue(payload["valid"])
        self.assertAlmostEqual(payload["x_m"], 2.50)
        self.assertAlmostEqual(payload["y_m"], -0.25)
        self.assertAlmostEqual(payload["z_m"], 0.10)

    def test_ball_position_camera_payload_is_flu(self) -> None:
        measurement = Ball3DMeasurement.valid_measurement(
            np.array([2.50, -0.25, 0.10], dtype=np.float64),
            source=MEASUREMENT_SOURCE_STEREO,
        )
        payload = build_ball_position_camera_payload(_packet(measurement))

        self.assertEqual(set(payload), {"type", "timestamp", "valid", "confidence", "x_m", "y_m", "z_m"})
        self.assertEqual(payload["type"], "ball_position_camera")
        self.assertTrue(payload["valid"])
        self.assertAlmostEqual(payload["x_m"], 2.50)
        self.assertAlmostEqual(payload["y_m"], -0.25)
        self.assertAlmostEqual(payload["z_m"], 0.10)


    def test_invalid_measurement_diagnostics_do_not_need_none_branch(self) -> None:
        measurement = _localize(_det(320, 240), None)
        diagnostics = build_ball_camera_diagnostics(_packet(measurement))

        self.assertEqual(diagnostics["measurement_source"], MEASUREMENT_SOURCE_STEREO)
        self.assertFalse(diagnostics["measurement_valid"])
        self.assertEqual(diagnostics["measurement_reject_reasons"], ["missing_stereo_pair"])
        self.assertEqual(diagnostics["measurement_quality"], 0.82)


if __name__ == "__main__":
    unittest.main()
