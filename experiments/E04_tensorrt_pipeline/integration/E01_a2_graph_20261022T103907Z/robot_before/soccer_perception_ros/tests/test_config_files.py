"""配置清单、跨文件合并和 launch 集成；不依赖 ROS、相机或模型。"""

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

import yaml

from soccer_perception import resources


class ConfigFileTests(unittest.TestCase):
    def test_parameter_file_annotations_are_deferred_for_python38(self):
        # Python 3.8 不能直接求值 Path | None 和 list[Path]。
        # 在较新解释器上也检查导入后的注解仍为字符串，防止漏掉延迟注解声明。
        for function in (resources.deployment_parameter_paths, resources.load_deployment_parameters):
            with self.subTest(function=function.__name__):
                self.assertIsInstance(function.__annotations__['manifest_path'], str)
                self.assertIsInstance(function.__annotations__['return'], str)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.manifest = self.root / 'camera_deploy.yaml'

    def write_manifest(self, files):
        self.manifest.write_text(yaml.safe_dump({'config_files': files}), encoding='utf-8')

    def write_params(self, name, params):
        path = self.root / name
        path.write_text(
            yaml.safe_dump({'soccer_perception_ros': {'ros__parameters': params}}),
            encoding='utf-8',
        )
        return path

    def test_merges_files_preserving_values_types_and_manifest_order(self):
        self.write_manifest(['detector.yaml', 'ros.yaml'])
        first = self.write_params('detector.yaml', {'det_conf': 0.0008, 'yolo_class_ids': '32', 'half': True})
        second = self.write_params('ros.yaml', {'deploy_packet_rate_hz': 15, 'frame_id': 'camera_flu'})
        self.assertEqual(resources.deployment_parameter_paths(self.manifest), [first, second])
        params = resources.load_deployment_parameters(self.manifest)
        self.assertEqual(params, {
            'det_conf': 0.0008, 'yolo_class_ids': '32', 'half': True,
            'deploy_packet_rate_hz': 15, 'frame_id': 'camera_flu',
        })
        self.assertIsInstance(params['yolo_class_ids'], str)
        self.assertIsInstance(params['half'], bool)
        self.assertIsInstance(params['deploy_packet_rate_hz'], int)
        self.write_params('ros.yaml', {'deploy_packet_rate_hz': 30})
        self.assertEqual(resources.load_deployment_parameters(self.manifest)['deploy_packet_rate_hz'], 30)

    def test_relative_file_paths_do_not_depend_on_current_directory(self):
        self.write_manifest(['camera.yaml'])
        self.write_params('camera.yaml', {'zed_resolution': 'VGA'})
        previous = Path.cwd()
        try:
            os.chdir(self.root.parent)
            self.assertEqual(resources.load_deployment_parameters(self.manifest), {'zed_resolution': 'VGA'})
        finally:
            os.chdir(previous)

    def test_manifest_shape_and_entries_are_checked(self):
        documents = [None, [], {}, {'config_files': []}, {'config_files': 'camera.yaml'},
                     {'config_files': [None]}, {'config_files': [True]}, {'config_files': [' ']},
                     {'config_files': ['camera.yaml'], 'unexpected': True}]
        for document in documents:
            with self.subTest(document=document):
                self.manifest.write_text(yaml.safe_dump(document), encoding='utf-8')
                with self.assertRaises(ValueError):
                    resources.deployment_parameter_paths(self.manifest)

    def test_missing_manifest_or_parameter_file_fails(self):
        with self.assertRaises(FileNotFoundError):
            resources.load_deployment_parameters(self.manifest)
        self.write_manifest(['missing.yaml'])
        with self.assertRaisesRegex(FileNotFoundError, 'missing.yaml'):
            resources.load_deployment_parameters(self.manifest)

    def test_duplicate_file_references_are_rejected(self):
        self.write_manifest(['camera.yaml', './camera.yaml'])
        self.write_params('camera.yaml', {'zed_resolution': 'VGA'})
        with self.assertRaisesRegex(ValueError, 'duplicate config file'):
            resources.deployment_parameter_paths(self.manifest)

    def test_duplicate_parameters_report_both_source_files(self):
        self.write_manifest(['camera.yaml', 'detector.yaml'])
        self.write_params('camera.yaml', {'zed_resolution': 'VGA'})
        self.write_params('detector.yaml', {'zed_resolution': 'HD720'})
        with self.assertRaises(ValueError) as caught:
            resources.load_deployment_parameters(self.manifest)
        for name in ('zed_resolution', 'camera.yaml', 'detector.yaml'):
            self.assertIn(name, str(caught.exception))

    def test_duplicate_keys_inside_yaml_are_rejected(self):
        self.write_manifest(['camera.yaml'])
        (self.root / 'camera.yaml').write_text(
            'soccer_perception_ros:\n  ros__parameters:\n    zed_gain: 1\n    zed_gain: 2\n',
            encoding='utf-8',
        )
        with self.assertRaisesRegex(ValueError, "duplicate key 'zed_gain'"):
            resources.load_deployment_parameters(self.manifest)
        self.manifest.write_text('config_files: []\nconfig_files: []\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, "duplicate key 'config_files'"):
            resources.deployment_parameter_paths(self.manifest)

    def test_parameter_file_shape_is_checked(self):
        self.write_manifest(['camera.yaml'])
        documents = [None, [], {'other_node': {'ros__parameters': {}}},
                     {'soccer_perception_ros': None}, {'soccer_perception_ros': {}},
                     {'soccer_perception_ros': {'ros__parameters': []}},
                     {'soccer_perception_ros': {'ros__parameters': {}, 'typo': {}}}]
        for document in documents:
            with self.subTest(document=document):
                (self.root / 'camera.yaml').write_text(yaml.safe_dump(document), encoding='utf-8')
                with self.assertRaises(ValueError):
                    resources.load_deployment_parameters(self.manifest)

    def test_installed_package_loads_manifest_and_sibling_files(self):
        self.write_manifest(['camera.yaml'])
        self.write_params('camera.yaml', {'zed_resolution': 'VGA'})
        packages = ModuleType('ament_index_python.packages')
        share = self.root / 'share/soccer_perception_ros'
        packages.get_package_share_directory = Mock(return_value=str(share))
        parent = ModuleType('ament_index_python')
        parent.packages = packages
        # 使用实际 share/<package>/config 的布局，验证常规安装时的路径解析。
        config_dir = share / 'config'
        config_dir.mkdir(parents=True)
        for name in ('camera_deploy.yaml', 'camera.yaml'):
            shutil.copyfile(self.root / name, config_dir / name)
        with patch.dict(sys.modules, {'ament_index_python': parent, 'ament_index_python.packages': packages}), \
             patch.object(resources, '__file__', str(self.root / 'lib/python3/site-packages/soccer_perception/resources.py')):
            self.assertEqual(resources.load_deployment_parameters(), {'zed_resolution': 'VGA'})
        packages.get_package_share_directory.assert_called_once_with('soccer_perception_ros')

    def test_launch_uses_manifest_from_active_installed_package(self):
        self.write_manifest(['detector.yaml', 'ros.yaml'])
        self.write_params('detector.yaml', {'yolo_class_ids': '32'})
        self.write_params('ros.yaml', {'frame_id': 'camera_flu'})
        share = self.root / 'share/soccer_perception_ros'
        config_dir = share / 'config'
        config_dir.mkdir(parents=True)
        for name in ('camera_deploy.yaml', 'detector.yaml', 'ros.yaml'):
            shutil.copyfile(self.root / name, config_dir / name)
        # launch 将原始 YAML 路径交给 ROS，保留带引号字符串等参数的 YAML 类型。
        packages = ModuleType('ament_index_python.packages')
        packages.get_package_share_directory = Mock(return_value=str(share))
        launch = ModuleType('launch')
        launch.LaunchDescription = Mock(side_effect=lambda actions: actions)
        actions = ModuleType('launch_ros.actions')
        actions.Node = Mock()
        script = Path(__file__).resolve().parents[1] / 'launch/soccer_perception.launch.py'
        modules = {'launch': launch, 'launch_ros': ModuleType('launch_ros'), 'launch_ros.actions': actions,
                   'ament_index_python': ModuleType('ament_index_python'), 'ament_index_python.packages': packages}
        # 使用真实清单解析器，只替换 ROS 提供的启动接口与包索引。
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('split_config_launch_test', script)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.generate_launch_description()
        packages.get_package_share_directory.assert_called_once_with('soccer_perception_ros')
        self.assertEqual(actions.Node.call_args.kwargs['parameters'],
                         [str(config_dir / 'detector.yaml'), str(config_dir / 'ros.yaml')])


if __name__ == '__main__':
    unittest.main()
