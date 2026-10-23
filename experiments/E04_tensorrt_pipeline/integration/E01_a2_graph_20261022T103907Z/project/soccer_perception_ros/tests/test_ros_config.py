import unittest
from dataclasses import fields
from pathlib import Path

import yaml

from soccer_perception.types import BackendConfig
from soccer_perception.ros.node import config_from_ros_params
from soccer_perception.resources import load_deployment_parameters


def _load_camera_deploy_params() -> dict:
    return load_deployment_parameters(_camera_deploy_config_path())


def _write_deployment_params(path: Path, params: dict) -> None:
    """测试用清单与参数文件，使用与部署一致的分文件加载入口。"""
    path.write_text(yaml.safe_dump({'config_files': ['parameters.yaml']}), encoding='utf-8')
    (path.parent / 'parameters.yaml').write_text(
        yaml.safe_dump({'soccer_perception_ros': {'ros__parameters': params}}), encoding='utf-8'
    )


def _camera_deploy_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "camera_deploy.yaml"


class FakeParameter:
    def __init__(self, value):
        self.value = value


class FakeRosNode:
    def __init__(self, params=None):
        self.params = params or {}
        self.read_names = []

    def declare_parameter(self, name, default=None):
        self.read_names.append(name)
        return FakeParameter(self.params.get(name, default))


class RosConfigTests(unittest.TestCase):
    def test_default_e01_engine_and_a2_graph_selection(self):
        config = config_from_ros_params()

        self.assertEqual(config.yolo_optimization, "a2_graph")
        self.assertEqual(config.yolo_model.name, "E01_baseline.engine")
        self.assertEqual(config.yolo_engine_path, config.yolo_model)
        self.assertEqual(config.yolo_class_ids, "0")
        self.assertEqual(config.det_conf, .45)
        self.assertEqual((config.imgsz, config.yolo_trt_batch), (640, 2))
        self.assertTrue(config.yolo_tensorrt)
        self.assertFalse(config.yolo_trt_dynamic)

    def test_optimization_modes_include_original_and_independent_fallbacks(self):
        for mode in ("none", "a2", "graph", "a2_graph"):
            with self.subTest(mode=mode):
                config = config_from_ros_params(FakeRosNode({"yolo_optimization": mode}))
                self.assertEqual(config.yolo_optimization, mode)
                self.assertEqual(config.yolo_model.name, "E01_baseline.engine")
                self.assertEqual(config.det_conf, .45)
        # Per-process ROS overrides never rewrite the selected YAML default.
        self.assertEqual(config_from_ros_params().yolo_optimization, "a2_graph")

    def test_optimization_requires_valid_string_without_silent_fallback(self):
        for value in ("", "baseline", "a1", "a2+graph", "A2", "a2_graph ", "reuse",
                      None, True, 1, 1.0, [], {}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "yolo_optimization"):
                    config_from_ros_params(FakeRosNode({"yolo_optimization": value}))

    def test_ros_bridge_reads_every_backend_config_field(self):
        fake = FakeRosNode()

        config_from_ros_params(fake)

        backend_fields = {field.name for field in fields(BackendConfig)}
        self.assertEqual(set(fake.read_names), backend_fields)

    def test_ros_bridge_uses_ros2_parameter_overrides(self):
        fake = FakeRosNode(
            {
                "deploy_packet_rate_hz": 30,
                "zed_brightness": "unchanged",
                "candidate_min_yolo_score": -1.0,
                "yolo_model": "/tmp/model.pt",
            }
        )

        config = config_from_ros_params(fake)

        self.assertEqual(config.deploy_packet_rate_hz, 30)
        self.assertIsNone(config.zed_brightness)
        self.assertIsNone(config.candidate_min_yolo_score)
        self.assertEqual(config.yolo_model, Path("/tmp/model.pt"))

    def test_camera_deploy_yaml_covers_every_backend_config_field(self):
        params = _load_camera_deploy_params()

        backend_fields = {field.name for field in fields(BackendConfig)}
        missing = sorted(backend_fields - set(params))
        self.assertEqual(missing, [])

    def test_camera_deploy_yaml_uses_current_deploy_param_names(self):
        params = _load_camera_deploy_params()

        self.assertIn("deploy_packet_rate_hz", params)
        self.assertIn("deploy_send_invalid_state", params)
        self.assertNotIn("robot_packet_rate_hz", params)
        self.assertNotIn("robot_send_invalid_state", params)
        self.assertEqual({name for name in params if 'fps' in name or 'rate_hz' in name},
                         {'deploy_packet_rate_hz', 'zed_fps'})
        self.assertNotIn('real_time', params)
        self.assertNotIn('real_time_factor', params)

    def test_camera_deploy_yaml_matches_piplus_ball_topic_contract(self):
        params = _load_camera_deploy_params()

        self.assertEqual(params["position_topic"], "ball_position")
        self.assertEqual(params["frame_id"], "camera_flu")
        self.assertEqual(params["json_topic"], "/soccer_perception/ball_position_camera_json")


class SplitYamlConfigTests(unittest.TestCase):
    def test_optimization_is_a_required_yaml_string(self):
        import tempfile
        from unittest.mock import patch
        field = next(field for field in fields(BackendConfig) if field.name == "yolo_optimization")
        self.assertEqual(str(field.type), "str")
        params = _load_camera_deploy_params()
        self.assertEqual(params["yolo_optimization"], "a2_graph")
        del params["yolo_optimization"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'camera_deploy.yaml'
            _write_deployment_params(path, params)
            with patch('soccer_perception.ros.node.deployment_config_path', return_value=path):
                with self.assertRaisesRegex(ValueError, 'missing parameters=.*yolo_optimization'):
                    config_from_ros_params()

    def test_runtime_fields_have_no_python_defaults(self):
        from dataclasses import MISSING
        for field in fields(BackendConfig):
            self.assertIs(field.default, MISSING, field.name)
            self.assertIs(field.default_factory, MISSING, field.name)

    def test_edited_yaml_changes_backend_and_ros_defaults(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'camera_deploy.yaml'
            params = _load_camera_deploy_params()
            params.update(deploy_packet_rate_hz=42, det_conf=0.123, frame_id='test_frame', publish_json=False)
            _write_deployment_params(path, params)
            with patch('soccer_perception.ros.node.deployment_config_path', return_value=path):
                first = config_from_ros_params()
                self.assertEqual((first.deploy_packet_rate_hz, first.det_conf, first.frame_id, first.publish_json),
                                 (42, 0.123, 'test_frame', False))
                params['deploy_packet_rate_hz'] = 43
                params['zed_fps'] = 60
                _write_deployment_params(path, params)
                self.assertEqual(config_from_ros_params().deploy_packet_rate_hz, 43)
                self.assertEqual(config_from_ros_params().zed_fps, 60)
                self.assertEqual(config_from_ros_params(FakeRosNode({'deploy_packet_rate_hz': 44})).deploy_packet_rate_hz, 44)

    def test_missing_and_unknown_yaml_fields_fail_without_fallback(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'camera_deploy.yaml'
            with patch('soccer_perception.ros.node.deployment_config_path', return_value=path):
                with self.assertRaises(FileNotFoundError):
                    config_from_ros_params()
                params = _load_camera_deploy_params()
                del params['deploy_packet_rate_hz']
                _write_deployment_params(path, params)
                with self.assertRaisesRegex(ValueError, 'missing parameters=.*deploy_packet_rate_hz'):
                    config_from_ros_params()
                params = _load_camera_deploy_params()
                params['typo_parameter'] = 1
                _write_deployment_params(path, params)
                with self.assertRaisesRegex(ValueError, 'unknown parameters=.*typo_parameter'):
                    config_from_ros_params()

    def test_yaml_location_does_not_depend_on_working_directory(self):
        import os
        import tempfile
        from soccer_perception.ros.node import deployment_config_path
        expected = deployment_config_path()
        old = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                self.assertEqual(deployment_config_path(), expected)
                self.assertEqual(config_from_ros_params().frame_id, 'camera_flu')
            finally:
                os.chdir(old)

    def test_optional_values_and_ros_scalar_types(self):
        config = config_from_ros_params(FakeRosNode({
            'zed_gain': -1, 'zed_exposure': 'unchanged',
            'yolo_engine_path': '', 'yolo_trt_workspace_gb': -1,
            'deploy_packet_rate_hz': 10, 'publish_json': 'false',
        }))
        self.assertEqual(config.zed_gain, -1)
        self.assertIsNone(config.zed_exposure)
        self.assertIsNone(config.yolo_engine_path)
        self.assertIsNone(config.yolo_trt_workspace_gb)
        self.assertEqual(config.deploy_packet_rate_hz, 10.)
        self.assertFalse(config.publish_json)

    def test_camera_fps_ros_override_and_validation(self):
        for fps in (0, 30, 60, 100):
            self.assertEqual(config_from_ros_params(FakeRosNode({'zed_fps': fps})).zed_fps, fps)
        for fps in (-1, 29.5, True, '100', None):
            with self.subTest(fps=fps), self.assertRaisesRegex(ValueError, 'zed_fps'):
                config_from_ros_params(FakeRosNode({'zed_fps': fps}))

    def test_output_frequency_must_be_positive_and_finite(self):
        for rate in (0, -1, float('nan'), float('inf')):
            with self.subTest(rate=rate):
                with self.assertRaisesRegex(ValueError, 'deploy_packet_rate_hz'):
                    config_from_ros_params(FakeRosNode({'deploy_packet_rate_hz': rate}))


if __name__ == "__main__":
    unittest.main()
