"""ROS 接口与资源生命周期回归；无需 ROS、GPU 或相机。"""
import builtins
import json
import sys
import unittest
from types import SimpleNamespace as NS, ModuleType
from unittest.mock import patch, Mock

import numpy as np

from dataclasses import replace
from soccer_perception.ros.node import config_from_ros_params

from soccer_perception.types import Ball3DMeasurement, json_safe
from soccer_perception.ros.output import build_ball_position_camera_payload
from soccer_perception.ros.node import RosBallStatePublisher, run_ros_node
from soccer_perception.adapters.zed import ZedFrameSource
from soccer_perception.adapters.viser import ZedRuntimeVisualizer
from tests.test_measurement_localization import _packet
from tests.test_ros_config import FakeRosNode
from tests.test_output_scheduler import FakeClock


def make_config(**overrides):
    return replace(config_from_ros_params(), **overrides)


class PointStamped:
    def __init__(self):
        self.header = NS(stamp=None, frame_id='')
        self.point = NS(x=0., y=0., z=0.)


class DataMessage:
    def __init__(self, data):
        self.data = data


class Node(FakeRosNode):
    def __init__(self, params=None):
        super().__init__(params)
        self.messages = {}

    def create_publisher(self, cls, topic, depth):
        self.messages[topic] = []
        return NS(publish=self.messages[topic].append)

    def get_clock(self):
        return NS(now=lambda: NS(to_msg=lambda: 'stamp'))

    def is_shutdown(self):
        return False


class RosRuntimeTests(unittest.TestCase):
    def setUp(self):
        geometry = ModuleType('geometry_msgs.msg')
        geometry.PointStamped = PointStamped
        std = ModuleType('std_msgs.msg')
        std.Bool = std.String = DataMessage
        self.modules = patch.dict(sys.modules, {'geometry_msgs.msg': geometry, 'std_msgs.msg': std})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def publisher(self, node, **overrides):
        args = dict(frame_id='camera_flu', position_topic='position', valid_topic='valid',
                    status_topic='status', json_topic='json', publish_json=True,
                    publish_invalid_position=False)
        args.update(overrides)
        return RosBallStatePublisher(node, **args)

    def test_valid_position_axes_timestamp_and_json(self):
        node = Node()
        publisher = self.publisher(node)
        payload = build_ball_position_camera_payload(_packet(
            Ball3DMeasurement.valid_measurement(np.array([2.5, -.25, .1]), source='stereo_triangulation')))
        publisher.publish(payload, {'measurement_source': 'stereo_triangulation'})
        point = node.messages['position'][0]
        self.assertEqual((point.point.x, point.point.y, point.point.z), (2.5, -.25, .1))
        self.assertEqual((point.header.frame_id, point.header.stamp), ('camera_flu', 'stamp'))
        self.assertTrue(node.messages['valid'][0].data)
        self.assertEqual(json.loads(node.messages['json'][0].data), payload)
        status = json.loads(node.messages['status'][0].data)
        self.assertEqual(status['axes'], {'x': 'front', 'y': 'left', 'z': 'up'})
        self.assertFalse(any(k.startswith('pointcloud_') for k in status))

    def test_invalid_state_preserves_publishing_policy(self):
        payload = build_ball_position_camera_payload(_packet(Ball3DMeasurement.invalid(source='stereo_triangulation', reject_reasons=['missing_stereo_pair'])))
        self.assertEqual([payload[k] for k in ('valid', 'confidence', 'x_m', 'y_m', 'z_m')], [False, 0., None, None, None])
        for send_position in (False, True):
            with self.subTest(send_position=send_position):
                node = Node(); publisher = self.publisher(node, publish_invalid_position=send_position)
                publisher.publish(payload)
                self.assertEqual(len(node.messages['position']), int(send_position))
                self.assertFalse(node.messages['valid'][0].data)
                self.assertEqual(json.loads(node.messages['json'][0].data), payload)
                if send_position:
                    p = node.messages['position'][0].point
                    self.assertEqual((p.x, p.y, p.z), (0., 0., 0.))

    def test_status_only_and_optional_json(self):
        payload = dict(valid=False, confidence=0., x_m=None, y_m=None, z_m=None, timestamp=1.)
        node = Node(); publisher = self.publisher(node)
        publisher.publish_status_only(payload)
        self.assertFalse(node.messages['valid'][0].data)
        self.assertEqual(node.messages['position'], [])
        self.assertEqual(node.messages['json'], [])
        self.assertTrue(json.loads(node.messages['status'][0].data)['dropped_json'])
        node = Node(); publisher = self.publisher(node, publish_json=False)
        publisher.publish(payload)
        self.assertNotIn('json', node.messages)

    def test_json_handles_numpy_boolean_nan_and_infinity(self):
        value = {'array': np.array([1., np.nan, np.inf]), 'flag': np.bool_(True), 'tuple': (np.int64(2), -float('inf'))}
        safe = json_safe(value)
        self.assertEqual(json.loads(json.dumps(safe, allow_nan=False)), {'array': [1., None, None], 'flag': True, 'tuple': [2, None]})
        self.assertEqual(json.loads(self.publisher(Node())._json(value).data), safe)

    def test_loop_paces_invalid_status_and_viser_without_dropping_frames(self):
        node = Node({'deploy_packet_rate_hz': 4., 'deploy_send_invalid_state': False})
        invalid = Ball3DMeasurement.invalid(source='stereo_triangulation', reject_reasons=['missing_stereo_pair'])
        packets = [_packet(invalid) for _ in range(4)]
        for packet, timestamp in zip(packets, (0., .1, .25, .3)):
            packet.timestamp = timestamp
        pipeline = Mock()
        clock = FakeClock()
        pending = iter(packets + [None])
        def next_packet():
            clock.advance(.06)
            return next(pending)
        pipeline.next_packet.side_effect = next_packet
        publish_times = []
        original_create = node.create_publisher
        def create_publisher(cls, topic, depth):
            handle = original_create(cls, topic, depth)
            if topic.endswith('/ball_valid'):
                original_publish = handle.publish
                def publish(message):
                    publish_times.append(clock.now)
                    original_publish(message)
                handle.publish = publish
            return handle
        node.create_publisher = create_publisher
        with patch('soccer_perception.ros.node.PipelineFactory') as factory, \
             patch('soccer_perception.ros.output.time.monotonic', clock.monotonic), \
             patch('soccer_perception.ros.output.time.sleep', clock.sleep):
            factory.return_value.create.return_value = pipeline
            run_ros_node(node)
        self.assertEqual(publish_times, [.25, .5, .75, 1.])
        self.assertEqual(len(node.messages['/soccer_perception/ball_valid']), 4)
        self.assertEqual(node.messages['ball_position'], [])
        self.assertEqual(node.messages['/soccer_perception/ball_position_camera_json'], [])
        self.assertEqual(pipeline.update_visualization.call_count, 4)
        status = json.loads(node.messages['/soccer_perception/ball_status'][-1].data)
        self.assertEqual(status['output_rate_hz'], 4.)
        pipeline.close.assert_called_once()

    def test_open_failure_still_releases_camera(self):
        pipeline = Mock(); pipeline.open.side_effect = RuntimeError('model load failed')
        with patch('soccer_perception.ros.node.PipelineFactory') as factory:
            factory.return_value.create.return_value = pipeline
            with self.assertRaisesRegex(RuntimeError, 'model load failed'):
                run_ros_node(Node())
        pipeline.close.assert_called_once()

    def test_disabled_viser_never_imports_optional_package(self):
        original = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name == 'viser' or name.startswith('viser.'):
                raise AssertionError('optional dependency imported')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=guarded):
            viewer = ZedRuntimeVisualizer(make_config(zed_viser_enabled=False))
            viewer.open()
            viewer.update(None, None)
            viewer.close()

    def test_sdk_depth_is_enabled_only_for_viser_point_cloud(self):
        for fps, viewer, show_cloud, mode, expected in (
            (0, False, True, 'QUALITY', 'NONE'),
            (30, True, False, 'QUALITY', 'NONE'),
            (60, True, True, 'NONE', 'NONE'),
            (100, True, True, 'QUALITY', 'QUALITY'),
        ):
            with self.subTest(viewer=viewer, show_cloud=show_cloud, mode=mode):
                sdk = ModuleType('pyzed.sl')
                sdk.RESOLUTION = NS(HD2K=0, HD1080=1, HD720=2, VGA=3)
                sdk.DEPTH_MODE = NS(NONE='NONE', PERFORMANCE='PERFORMANCE', QUALITY='QUALITY', ULTRA='ULTRA')
                sdk.UNIT = NS(METER='m')
                sdk.ERROR_CODE = NS(SUCCESS=0)
                sdk.InitParameters = lambda **kwargs: NS(**kwargs)
                sdk.RuntimeParameters = sdk.Mat = object
                camera = Mock()
                camera.open.return_value = 0
                calibration = NS(left_cam=NS(fx=600., fy=600., cx=320., cy=240.), get_camera_baseline=lambda: .12)
                camera.get_camera_information.return_value = NS(camera_configuration=NS(
                    calibration_parameters=calibration, fps=30., resolution=NS(width=640, height=480)))
                sdk.Camera = lambda: camera
                parent = ModuleType('pyzed'); parent.sl = sdk
                source = ZedFrameSource(make_config(zed_fps=fps, zed_viser_enabled=viewer, zed_viser_show_point_cloud=show_cloud, zed_depth_mode=mode))
                with patch.dict(sys.modules, {'pyzed': parent, 'pyzed.sl': sdk}):
                    source.open()
                self.assertEqual(camera.open.call_args.args[0].depth_mode, expected)
                self.assertEqual(camera.open.call_args.args[0].camera_fps, fps)
                self.assertEqual(source._xyzrgba_mat is not None, expected != 'NONE')
                source.close()
                camera.close.assert_called_once()

    def test_camera_retrieves_only_optional_visualization_cloud(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                source = ZedFrameSource(make_config(zed_viser_enabled=enabled))
                source._sl = NS(ERROR_CODE=NS(SUCCESS=0), VIEW=NS(LEFT='left', RIGHT='right'), MEASURE=NS(XYZRGBA='cloud'))
                source._runtime = object()
                source._cam = Mock(); source._cam.grab.return_value = 0; source._cam.retrieve_measure.return_value = 0
                source._left_mat = source._right_mat = NS(get_data=lambda: np.zeros((2, 2, 4), np.uint8))
                source._depth_enabled = enabled; source._xyzrgba_mat = object()
                frame = source.read()
                self.assertEqual(source._cam.retrieve_measure.call_count, int(enabled))
                self.assertEqual(frame.zed_xyzrgba is not None, enabled)
                if enabled:
                    source._cam.retrieve_measure.assert_called_with(source._xyzrgba_mat, 'cloud')
                source.close()
                source._cam = Mock(); source._cam.grab.return_value = 1
                with self.assertRaisesRegex(RuntimeError, 'ZED grab failed'):
                    source.read()


if __name__ == '__main__':
    unittest.main()
