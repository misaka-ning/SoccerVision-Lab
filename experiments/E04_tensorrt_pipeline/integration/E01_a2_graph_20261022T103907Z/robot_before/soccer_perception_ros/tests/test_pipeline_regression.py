"""固定输入与瘦身前基线逐帧对照，不依赖硬件。"""
import json
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from soccer_perception.types import StereoFrame
from soccer_perception.pipeline import SoccerPerceptionPipeline
from soccer_perception.core.tracking import AlphaBetaBallTracker
from soccer_perception.ros.output import build_ball_position_camera_payload
from soccer_perception.ros.node import config_from_ros_params
from tests.test_ros_config import FakeRosNode, _load_camera_deploy_params
from tests.test_measurement_localization import _det, _triangulator


class Source:
    def __init__(self, count):
        self.count = count
        self.index = 0
        self.closed = False

    def open(self):
        return _triangulator().intrinsics

    def read(self):
        if self.index >= self.count:
            return None
        image = np.zeros((480, 640, 3), np.uint8)
        frame = StereoFrame(timestamp=1 + self.index / 30, left=image, right=image, frame_idx=self.index)
        self.index += 1
        return frame

    def close(self):
        self.closed = True


class Detector:
    name = 'fixture'

    def __init__(self, pairs):
        self.pairs = iter(pairs)

    def load(self):
        pass

    def detect_candidates_batch(self, frames, top_k):
        return next(self.pairs)


class PipelineRegressionTests(unittest.TestCase):
    def test_tracking_loss_and_recovery_match_original_outputs(self):
        # 此基线记录原始跟踪器的输出，关闭部署层的短时漏检门控，
        # 以便逐帧比较检测丢失、预测延续、跟踪失效及重新检测后的恢复结果。
        config = replace(
            config_from_ros_params(FakeRosNode(_load_camera_deploy_params())),
            zed_viser_enabled=False,
            short_loss_tolerance_enabled=False,
        )
        pairs = [([_det(320 + i, 240)], [_det(280 + i, 240)]) for i in range(4)]
        pairs += [([_det(200, 240)], [_det(280, 240)]), ([_det(320, 240)], [])]
        pairs += [([], [])] * 40
        pairs += [([_det(330, 235)], [_det(290, 235)])] * 3
        source = Source(len(pairs))
        pipeline = SoccerPerceptionPipeline(
            source, Detector(pairs), AlphaBetaBallTracker(
                max_coast_frames=config.max_coast_frames,
                max_coast_time_s=config.max_coast_time_s,
                velocity_decay=config.velocity_decay), config)
        actual = []
        try:
            pipeline.open()
            while True:
                packet = pipeline.next_packet()
                if packet is None:
                    break
                measurement = packet.ball_3d_measurement.to_dict()
                actual.append(dict(
                    payload=build_ball_position_camera_payload(packet),
                    mode=packet.camera_track_mode,
                    velocity=None if packet.camera_velocity_mps is None else packet.camera_velocity_mps.tolist(),
                    measurement=measurement['position_camera_m'],
                    reject_reasons=measurement['reject_reasons']))
        finally:
            pipeline.close()
        expected = json.loads((Path(__file__).parent / 'fixtures' / 'stereo_sequence_expected.json').read_text())
        self.assertEqual(actual, expected)
        self.assertEqual({item['mode'] for item in actual}, {'TRACKED', 'OCCLUDED_PREDICT', 'LOST'})
        self.assertTrue(source.closed)


if __name__ == '__main__':
    unittest.main()
