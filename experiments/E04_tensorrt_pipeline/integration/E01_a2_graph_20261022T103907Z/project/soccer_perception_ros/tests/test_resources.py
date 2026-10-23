"""Source and installed resource paths must not depend on the current directory."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

from soccer_perception import resources
from soccer_perception.ros.node import config_from_ros_params


class ResourcePathTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop('SOCCER_MODEL_DIR', None)

    def test_source_configuration_and_models_resolve_from_any_directory(self):
        package = Path(__file__).resolve().parents[1]
        params = resources.load_deployment_parameters(package / 'config/camera_deploy.yaml')
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                config = config_from_ros_params()
                self.assertEqual(resources.deployment_config_path(), package / 'config/camera_deploy.yaml')
                # Model names are deployment settings; verify path resolution independently.
                for name in ('yolo_model', 'yolo_engine_path'):
                    with self.subTest(parameter=name):
                        configured_path = Path(params[name]).expanduser()
                        expected = (package / configured_path).resolve()
                        self.assertEqual(getattr(config, name), expected)
                # Engine is device-specific deployment data, not a source
                # checkout prerequisite. Its existence is checked by load().
                self.assertEqual(config.yolo_model.parent, resources.model_directory())
            finally:
                os.chdir(previous)

    def test_absolute_model_override_and_home_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'external.engine'
            self.assertEqual(resources.resolve_resource_path(str(path)), path)
        self.assertEqual(resources.resolve_resource_path('~/model.engine'), Path.home() / 'model.engine')

    def test_installed_resources_use_ament_package_index(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            share = prefix / 'share/soccer_perception_ros'
            share.mkdir(parents=True)
            models = prefix / 'source/models'
            models.mkdir(parents=True)
            (share / 'source_models_directory.txt').write_text(str(models))
            packages = ModuleType('ament_index_python.packages')
            lookup = Mock(return_value=str(share))
            packages.get_package_share_directory = lookup
            parent = ModuleType('ament_index_python'); parent.packages = packages
            with patch.dict(sys.modules, {'ament_index_python': parent, 'ament_index_python.packages': packages}), \
                 patch.object(resources, '__file__', str(prefix / 'lib/python3/site-packages/soccer_perception/resources.py')):
                self.assertEqual(resources.deployment_config_path(), share / 'config/camera_deploy.yaml')
                self.assertEqual(resources.resolve_resource_path('models/yolo26s.pt'), models / 'yolo26s.pt')
            self.assertEqual(lookup.call_count, 2)
            lookup.assert_called_with('soccer_perception_ros')

    def test_model_override_is_shared_by_source_and_install_and_resolves_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / 'models'; models.mkdir()
            link = root / 'link'; link.symlink_to(models, target_is_directory=True)
            with patch.dict(os.environ, {'SOCCER_MODEL_DIR': str(link)}):
                expected = models / 'ball.engine'
                self.assertEqual(resources.resolve_resource_path('models/ball.engine'), expected)
                with patch.object(resources, '__file__', '/unrelated/install/resources.py'):
                    self.assertEqual(resources.resolve_resource_path('models/ball.engine'), expected)
                    self.assertEqual(resources.resolve_resource_path('ball.engine'), expected)
            with patch.dict(os.environ, {'SOCCER_MODEL_DIR': 'relative/models'}):
                with self.assertRaisesRegex(ValueError, 'absolute'):
                    resources.model_directory()
            with patch.dict(os.environ, {'SOCCER_MODEL_DIR': str(root / 'missing')}):
                with self.assertRaisesRegex(FileNotFoundError, 'unavailable'):
                    resources.model_directory()

    def test_relocated_install_does_not_silently_generate_in_install(self):
        with tempfile.TemporaryDirectory() as directory:
            share = Path(directory)
            with patch.object(resources, 'package_share_directory', return_value=share):
                with self.assertRaisesRegex(RuntimeError, 'SOCCER_MODEL_DIR'):
                    resources.resolve_resource_path('models/ball.engine')
                (share / 'source_models_directory.txt').write_text(str(share / 'missing'))
                with self.assertRaisesRegex(FileNotFoundError, 'SOCCER_MODEL_DIR'):
                    resources.resolve_resource_path('models/ball.engine')

    def test_node_entry_uses_installed_import_without_changing_process_paths(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/soccer_perception_ros_node.py'
        spec = importlib.util.spec_from_file_location('node_entry_test', script)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        previous_dir, previous_path = Path.cwd(), list(sys.path)
        with patch.object(module, '_ensure_runtime_python') as prepare, patch('soccer_perception.ros.node.main') as main:
            module.main()
        prepare.assert_called_once()
        main.assert_called_once()
        self.assertEqual(Path.cwd(), previous_dir)
        self.assertEqual(sys.path, previous_path)

    def test_node_dependency_check_rejects_broken_lazy_yolo_import(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/soccer_perception_ros_node.py'
        spec = importlib.util.spec_from_file_location('node_dependency_test', script)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        ultralytics = ModuleType('ultralytics')
        def lazy_import(name):
            if name == 'YOLO':
                raise ImportError('mixed matplotlib namespace: rcParams')
            raise AttributeError(name)
        ultralytics.__getattr__ = lazy_import
        pyzed = ModuleType('pyzed'); pyzed.__path__ = []
        stubs = {'rclpy': ModuleType('rclpy'), 'ament_index_python': ModuleType('ament_index_python'),
                 'pyzed': pyzed, 'pyzed.sl': ModuleType('pyzed.sl'), 'ultralytics': ultralytics}
        with patch.dict(sys.modules, stubs):
            self.assertFalse(module._has_runtime_deps())
            ultralytics.YOLO = object()
            self.assertTrue(module._has_runtime_deps())

    def test_node_switches_to_venv_even_when_python_binary_is_the_same(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/soccer_perception_ros_node.py'
        spec = importlib.util.spec_from_file_location('node_venv_test', script)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            venv_python = Path(directory) / 'bin/python'
            venv_python.parent.mkdir()
            venv_python.symlink_to(sys.executable)
            self.assertEqual(venv_python.resolve(), Path(sys.executable).resolve())
            with patch.dict(os.environ, {'SOCCER_PERCEPTION_PYTHON': str(venv_python)}), \
                 patch.object(module, '_python_has_runtime_deps', return_value=True) as check, \
                 patch.object(module, '_ensure_zed_library_path') as prepare, \
                 patch.object(module.os, 'execv', side_effect=RuntimeError('venv reexec')) as execute:
                with self.assertRaisesRegex(RuntimeError, 'venv reexec'):
                    module._ensure_runtime_python()
            check.assert_called_once_with(str(venv_python))
            prepare.assert_called_once_with(venv_python)
            execute.assert_called_once_with(str(venv_python), [str(venv_python), *sys.argv])


if __name__ == '__main__':
    unittest.main()
