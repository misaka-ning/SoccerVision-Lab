"""按部署清单加载各职责参数文件，启动 ROS 2 足球感知节点。"""

from __future__ import annotations

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node

from soccer_perception.resources import deployment_parameter_paths


def generate_launch_description() -> LaunchDescription:
    # 显式定位当前 ROS 工作区安装的清单，使用与节点相同的文件列表解析规则。
    manifest = Path(get_package_share_directory("soccer_perception_ros")) / "config" / "camera_deploy.yaml"
    configs = deployment_parameter_paths(manifest)

    return LaunchDescription(
        [
            Node(
                package="soccer_perception_ros",
                executable="soccer_perception_ros_node.py",
                name="soccer_perception_ros",
                output="screen",
                parameters=[str(path) for path in configs],
            ),
        ]
    )
