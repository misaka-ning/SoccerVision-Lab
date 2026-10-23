#!/usr/bin/env python3
"""ROS 2 节点入口：准备 Python 运行环境，再调用已安装的足球感知包。

launch 文件启动此脚本；本文件负责解释器选择和依赖检查，
实际的 ROS 节点创建、感知流程和话题发布由 soccer_perception.ros.node 执行。
"""

from __future__ import annotations

import sys
import os
import shutil
import subprocess
from pathlib import Path

# ZED SDK 的动态链接库目录。
ZED_LIB = "/usr/local/zed/lib"


def _interpreter_path(value: str) -> Path:
    """展开 ~ 并转为绝对路径，同时保留虚拟环境解释器的符号链接。

    不使用 resolve()，避免把虚拟环境中的 Python 链接解析成系统 Python 路径，
    导致后续无法区分两个运行环境。
    """
    return Path(value).expanduser().absolute()


def _ensure_runtime_python() -> None:
    """确保使用具备项目依赖的 Python，必要时切换解释器重新执行本脚本。"""

    # 优先使用环境变量指定的 Python；指定其他解释器时，先检查其依赖。
    explicit = os.environ.get("SOCCER_PERCEPTION_PYTHON")
    if explicit:
        explicit = str(_interpreter_path(explicit))
    if explicit and _interpreter_path(explicit) != _interpreter_path(sys.executable):
        if not _python_has_runtime_deps(explicit):
            raise RuntimeError(f"SOCCER_PERCEPTION_PYTHON lacks runtime dependencies: {explicit}")
        _ensure_zed_library_path(Path(explicit))
        # 用指定解释器替换当前进程，并保留原始参数（包括 ROS 启动参数）。
        os.execv(explicit, [explicit, *sys.argv])
    # 当前解释器可用时，补充动态库路径后继续启动。
    if _has_runtime_deps():
        _ensure_zed_library_path(Path(sys.executable))
        return

    # 当前环境缺少依赖时，依次检查候选解释器，跳过已经检查过的当前解释器。
    for candidate in _python_candidates():
        if candidate and _interpreter_path(candidate) == _interpreter_path(sys.executable):
            continue
        if _python_has_runtime_deps(candidate):
            _ensure_zed_library_path(Path(candidate))
            os.execv(candidate, [candidate, *sys.argv])

    # 所有候选环境都不可用时，给出配置解释器的提示。
    raise RuntimeError(
        "No Python environment with the installed soccer_perception package and ROS/ZED/YOLO dependencies was found. "
        f"Current python={sys.executable}. "
        "Set SOCCER_PERCEPTION_PYTHON=/path/to/python or activate the correct environment before launching. "
        "The viser package is only required when zed_viser_enabled is true."
    )


def _has_runtime_deps() -> bool:
    """通过实际导入，检查当前 Python 是否具备 ROS、ZED、YOLO 和项目依赖。"""
    try:
        import rclpy  # noqa: F401
        import yaml  # noqa: F401
        import ament_index_python  # noqa: F401
        import soccer_perception  # noqa: F401
        import pyzed.sl  # noqa: F401
        # Ultralytics 延迟加载 YOLO，仅导入顶层包不足以验证 YOLO 能否使用。
        # 这里直接导入 YOLO，以发现机器人上曾出现的 Matplotlib 命名空间混用问题。
        from ultralytics import YOLO  # noqa: F401
    except Exception:
        return False
    return True


def _python_candidates() -> list[str]:
    """按优先顺序列出指定解释器、PATH 中的 Python 和系统 Python。"""
    return [
        os.environ.get("SOCCER_PERCEPTION_PYTHON", ""),
        shutil.which("python3") or "",
        shutil.which("python") or "",
        "/usr/bin/python3",
    ]


def _python_has_runtime_deps(candidate: str) -> bool:
    """启动候选 Python 子进程，检查它能否导入运行所需的依赖。"""
    if not candidate or not Path(candidate).is_file():
        return False
    env = os.environ.copy()
    # Jetson 上的 CUDA torch/torchvision 安装在用户 site-packages 中，
    # ultralytics 则位于感知虚拟环境。检查子进程时移除 PYTHONNOUSERSITE，
    # 避免继承的 systemd/conda 设置屏蔽用户依赖，导致可用环境被误判。
    env.pop("PYTHONNOUSERSITE", None)
    python_path = Path(candidate)
    env_dir = python_path.parent.parent
    # 为检查子进程补充环境 lib 和 ZED SDK 库目录，并保留已有库路径。
    entries = [str(env_dir / "lib"), ZED_LIB]
    current = env.get("LD_LIBRARY_PATH", "")
    if current:
        entries.append(current)
    env["LD_LIBRARY_PATH"] = os.pathsep.join(entries)
    command = "import rclpy; import pyzed.sl; from ultralytics import YOLO; import yaml; import ament_index_python; import soccer_perception"
    # 使用候选解释器执行导入检查；隐藏检查输出，通过退出码判断是否成功。
    result = subprocess.run(
        [candidate, "-c", command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        check=False,
    )
    return result.returncode == 0


def _ensure_zed_library_path(python_path: Path) -> None:
    """为当前进程及后续子进程补充 Python 环境和 ZED 的动态库搜索路径。"""
    env_dir = python_path.parent.parent
    entries = [str(env_dir / "lib"), ZED_LIB]
    current = os.environ.get("LD_LIBRARY_PATH", "")
    if current:
        entries.append(current)
    os.environ["LD_LIBRARY_PATH"] = ":".join(entries)


def main() -> None:
    """先准备运行环境，再进入实际的 ROS 感知节点。"""
    _ensure_runtime_python()
    # 环境检查通过后再导入节点；使用别名，避免与本文件的 main() 混淆。
    from soccer_perception.ros.node import main as ros_bridge_main

    ros_bridge_main()


if __name__ == "__main__":
    # 作为脚本执行时启动；作为模块导入时不自动运行。
    main()
