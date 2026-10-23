from __future__ import annotations

import unittest

import numpy as np

from soccer_perception.core.candidate_selection import StereoCandidateSelector
from dataclasses import replace
from soccer_perception.ros.node import config_from_ros_params

from soccer_perception.core.geometry import StereoTriangulator
from soccer_perception.types import BallDetection, CameraIntrinsics


def make_config(**overrides):
    return replace(config_from_ros_params(), **overrides)


def _det(
    u: float,
    v: float,
    *,
    radius: float = 20.0,
    score: float = 0.8,
    bbox: tuple[int, int, int, int] | None = None,
    source: str = "yolo",
) -> BallDetection:
    if bbox is None:
        bbox = (int(round(u - radius)), int(round(v - radius)), int(round(radius * 2.0)), int(round(radius * 2.0)))
    return BallDetection(
        center=np.array([u, v], dtype=np.float64),
        radius_px=radius,
        score=score,
        bbox=bbox,
        source=source,
    )


def _triangulator() -> StereoTriangulator:
    intrinsics = CameraIntrinsics(
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
    )
    return StereoTriangulator(intrinsics, max_vertical_delta_px=12.0, vertical_radius_factor=0.5)


class StereoCandidateSelectorTest(unittest.TestCase):
    def test_selects_highest_scored_valid_pair(self) -> None:
        selector = StereoCandidateSelector(make_config(candidate_bbox_gate_enabled=True))
        result = selector.select(
            [_det(320, 240, score=0.3), _det(300, 240, score=0.9)],
            [_det(280, 240, score=0.3), _det(260, 240, score=0.9)],
            _triangulator(),
            source="test",
        )

        self.assertIsNotNone(result.left)
        self.assertIsNotNone(result.right)
        self.assertAlmostEqual(float(result.left.score), 0.9)
        self.assertEqual(result.diagnostics["pair_count_before"], 4)
        self.assertEqual(result.diagnostics["pair_count_after"], 4)
        self.assertEqual(result.diagnostics["pair_reject_reasons"], {})

    def test_rejects_invalid_monocular_bbox(self) -> None:
        selector = StereoCandidateSelector(make_config(candidate_bbox_gate_enabled=True))
        result = selector.select(
            [_det(320, 240, bbox=(10, 10, 0, 20))],
            [_det(280, 240)],
            _triangulator(),
            source="test",
        )

        self.assertIsNone(result.left)
        self.assertEqual(result.diagnostics["left_count_before"], 1)
        self.assertEqual(result.diagnostics["left_count_after"], 0)
        self.assertEqual(result.diagnostics["monocular_reject_reasons"], {"bbox_invalid_size": 1})

    def test_rejects_bbox_outside_image(self) -> None:
        selector = StereoCandidateSelector(make_config(candidate_bbox_gate_enabled=True))
        result = selector.select(
            [_det(900, 240, bbox=(700, 20, 30, 30))],
            [_det(280, 240)],
            _triangulator(),
            source="test",
        )

        self.assertIsNone(result.left)
        self.assertEqual(result.diagnostics["monocular_reject_reasons"], {"bbox_outside_image": 1})

    def test_rejects_bad_aspect_ratio_and_too_large_bbox(self) -> None:
        selector = StereoCandidateSelector(
            make_config(
                candidate_bbox_gate_enabled=True,
                candidate_bbox_max_area_ratio=0.3,
                candidate_bbox_min_aspect_ratio=0.5,
                candidate_bbox_max_aspect_ratio=2.0,
            )
        )
        result = selector.select(
            [_det(320, 240, bbox=(10, 10, 10, 100)), _det(320, 240, bbox=(0, 0, 640, 480))],
            [_det(280, 240)],
            _triangulator(),
            source="test",
        )

        self.assertIsNone(result.left)
        self.assertEqual(
            result.diagnostics["monocular_reject_reasons"],
            {"bbox_bad_aspect_ratio": 1, "bbox_too_large": 1},
        )

    def test_score_gate_only_applies_confidence_detectors(self) -> None:
        selector = StereoCandidateSelector(
            make_config(
                candidate_score_gate_enabled=True,
                candidate_min_yolo_score=0.5,
            )
        )
        result = selector.select(
            [_det(320, 240, score=0.1, source="yolo"), _det(320, 240, score=0.1, source="test_detector")],
            [_det(280, 240, score=0.1, source="test_detector")],
            _triangulator(),
            source="test",
        )

        self.assertIsNotNone(result.left)
        self.assertEqual(result.left.source, "test_detector")
        self.assertEqual(result.diagnostics["monocular_reject_reasons"], {"score_below_threshold": 1})

    def test_rejects_bad_disparity_vertical_and_radius_mismatch(self) -> None:
        tri = _triangulator()
        selector = StereoCandidateSelector(make_config(candidate_bbox_gate_enabled=True, candidate_max_radius_ratio=1.5))

        bad_disparity = selector.select([_det(250, 240)], [_det(280, 240)], tri, source="test")
        self.assertEqual(bad_disparity.diagnostics["pair_reject_reasons"], {"bad_disparity": 1})

        vertical = selector.select([_det(320, 240)], [_det(280, 270)], tri, source="test")
        self.assertEqual(vertical.diagnostics["pair_reject_reasons"], {"vertical_mismatch": 1})

        radius = selector.select([_det(320, 240, radius=35)], [_det(280, 240, radius=10)], tri, source="test")
        self.assertEqual(radius.diagnostics["pair_reject_reasons"], {"radius_mismatch": 1})

    def test_rejects_depth_outside_configured_range(self) -> None:
        tri = _triangulator()
        selector = StereoCandidateSelector(make_config(candidate_min_depth_m=1.0, candidate_max_depth_m=1.2))

        too_far = selector.select([_det(320, 240)], [_det(280, 240)], tri, source="test")
        self.assertEqual(too_far.diagnostics["pair_reject_reasons"], {"depth_too_far": 1})

        too_near = selector.select([_det(500, 240)], [_det(300, 240)], tri, source="test")
        self.assertEqual(too_near.diagnostics["pair_reject_reasons"], {"depth_too_near": 1})

    def test_radius_consistency_can_hard_reject(self) -> None:
        selector = StereoCandidateSelector(
            make_config(
                candidate_radius_consistency_enabled=True,
                candidate_radius_consistency_hard_gate=True,
                candidate_radius_consistency_tolerance_ratio=0.1,
                candidate_expected_ball_radius_m=0.11,
            )
        )
        result = selector.select(
            [_det(320, 240, radius=8)],
            [_det(280, 240, radius=8)],
            _triangulator(),
            source="test",
        )

        self.assertEqual(result.diagnostics["pair_reject_reasons"], {"radius_consistency_mismatch": 1})
        self.assertIn("radius_consistency_ratio", result.diagnostics["best_rejected_metrics"])

    def test_prediction_3d_jump_and_speed_hard_gate_are_explicit(self) -> None:
        jump_selector = StereoCandidateSelector(
            make_config(
                candidate_max_3d_jump_m=0.2,
                candidate_max_speed_mps=2.0,
            )
        )
        jump = jump_selector.select(
            [_det(320, 240)],
            [_det(280, 240)],
            _triangulator(),
            source="test",
            previous_camera_position_m=np.array([0.0, 0.0, 3.0], dtype=np.float64),
            previous_timestamp=0.0,
            current_timestamp=0.1,
        )

        self.assertEqual(jump.diagnostics["pair_reject_reasons"], {"camera_3d_jump_too_large": 1})

        speed_selector = StereoCandidateSelector(make_config(candidate_max_speed_mps=2.0))
        speed = speed_selector.select(
            [_det(320, 240)],
            [_det(280, 240)],
            _triangulator(),
            source="test",
            previous_camera_position_m=np.array([0.0, 0.0, 1.4], dtype=np.float64),
            previous_timestamp=0.0,
            current_timestamp=0.1,
        )

        self.assertEqual(speed.diagnostics["pair_reject_reasons"], {"camera_speed_too_large": 1})


if __name__ == "__main__":
    unittest.main()
