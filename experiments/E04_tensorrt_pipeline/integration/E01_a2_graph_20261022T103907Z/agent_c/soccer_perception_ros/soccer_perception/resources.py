"""解析源码或安装目录中的包资源，统一读取部署清单和各职责参数文件。"""

from __future__ import annotations

import os
from pathlib import Path

import yaml


class _UniqueKeyLoader(yaml.SafeLoader):
    """拒绝同一 YAML 映射中的重复键，避免解析时静默覆盖参数。"""

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        keys = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ValueError(f"{key_node.start_mark}: expected a string key")
            if key in keys:
                raise ValueError(f"{key_node.start_mark}: duplicate key {key!r}")
            keys.add(key)
        return super().construct_mapping(node, deep=deep)


def _read_yaml(path: Path):
    """安全读取 YAML，并在重复键或格式错误中保留文件定位信息。"""
    with path.open(encoding='utf-8') as stream:
        return yaml.load(stream, Loader=_UniqueKeyLoader)


def package_share_directory() -> Path:
    # Source checkout (including a symlink install): one known package boundary.
    source = Path(__file__).resolve().parent.parent
    if (source / 'package.xml').is_file():
        return source

    # Normal installation: let ROS resolve the active overlay's package assets.
    from ament_index_python.packages import get_package_share_directory
    return Path(get_package_share_directory('soccer_perception_ros'))


def deployment_config_path() -> Path:
    """定位部署文件清单；具体参数保存在清单列出的职责文件中。"""
    return package_share_directory() / 'config' / 'camera_deploy.yaml'


def deployment_parameter_paths(manifest_path: Path | None = None) -> list[Path]:
    """读取清单，返回参数文件的绝对路径，供 launch 和节点共同使用。

    相对路径按清单目录解析，不受当前工作目录影响；清单格式错误、
    文件缺失或重复列出同一文件时直接报错。
    """
    manifest = Path(manifest_path or deployment_config_path()).resolve()
    document = _read_yaml(manifest)
    if not isinstance(document, dict) or set(document) != {'config_files'}:
        raise ValueError(f"{manifest}: expected only config_files")
    files = document['config_files']
    if not isinstance(files, list) or not files:
        raise ValueError(f"{manifest}: config_files must be a non-empty list")
    paths = []
    for name in files:
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{manifest}: config_files entries must be non-empty strings")
        path = (manifest.parent / name).resolve()
        if path in paths:
            raise ValueError(f"{manifest}: duplicate config file {path}")
        if not path.is_file():
            raise FileNotFoundError(f"{manifest}: config file not found: {path}")
        paths.append(path)
    return paths


def load_deployment_parameters(manifest_path: Path | None = None) -> dict:
    """合并各职责文件的 ROS 参数；同一参数跨文件重复定义时也报错。

    这里只检查文件结构及重复项；BackendConfig 字段完整性和类型由节点校验。
    每次调用都重新读取，确保修改 YAML 后不会使用缓存中的旧值。
    """
    params = {}
    sources = {}
    for path in deployment_parameter_paths(manifest_path):
        document = _read_yaml(path)
        if not isinstance(document, dict) or set(document) != {'soccer_perception_ros'}:
            raise ValueError(f"{path}: expected only soccer_perception_ros")
        section = document['soccer_perception_ros']
        if not isinstance(section, dict) or set(section) != {'ros__parameters'}:
            raise ValueError(f"{path}: expected soccer_perception_ros.ros__parameters")
        values = section['ros__parameters']
        if not isinstance(values, dict):
            raise ValueError(f"{path}: ros__parameters must be a mapping")
        for name, value in values.items():
            if name in params:
                raise ValueError(f"duplicate parameter {name!r}: {sources[name]} and {path}")
            params[name] = value
            sources[name] = path
    return params


def model_directory() -> Path:
    """One writable model directory for source and installed execution."""
    override = os.environ.get('SOCCER_MODEL_DIR')
    if override:
        directory = Path(override).expanduser()
        if not directory.is_absolute():
            raise ValueError('SOCCER_MODEL_DIR must be an absolute path')
    else:
        share = package_share_directory()
        marker = share / 'source_models_directory.txt'
        # CMake records the source directory even for a normal copy install.
        directory = Path(marker.read_text(encoding='utf-8').strip()) if marker.is_file() else share / 'models'
        if not (share / 'soccer_perception').is_dir() and not marker.is_file():
            raise RuntimeError('Model directory is not configured. Rebuild the ROS package or set '
                               'SOCCER_MODEL_DIR to the absolute path of your model directory.')
    if not directory.is_absolute() or not directory.is_dir():
        raise FileNotFoundError(f'Model directory unavailable: {directory}. '
                                'Set SOCCER_MODEL_DIR when relocating an installation.')
    return directory.resolve()


def resolve_resource_path(value: str) -> Path:
    """Resolve model paths independently of the install tree and working directory."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    # Preserve existing YAML spelling: models/name.pt refers to the model root.
    relative = Path(*path.parts[1:]) if path.parts and path.parts[0] == 'models' else path
    return (model_directory() / relative).resolve()
