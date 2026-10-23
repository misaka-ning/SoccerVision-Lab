# Jetson 部署

在项目根目录执行下列命令。目标设备须已安装匹配的 NVIDIA 驱动、CUDA、ZED SDK 和 ROS2。
依赖脚本保留现有 Jetson / x86 策略，不自动升级部署栈；版本集中在 `deployment/dependencies.sh`。

1. 按 `soccer_perception_ros/models/README.md` 恢复并校验模型。
2. 执行 `bash deployment/setup_dependencies.sh --check-only` 检查依赖；缺失时执行 `bash deployment/setup_dependencies.sh`。
3. 按职责修改 `soccer_perception_ros/config/` 下的参数文件；例如模型阈值在 `detector.yaml`，输出频率与话题在 `ros.yaml`。`camera_deploy.yaml` 仅列出需要加载的文件。
4. 执行 `bash deployment/build_project.sh`，在本目录产生 `build/`、`install/`、`log/` 并运行测试。
5. 使用 TensorRT 时，在目标设备执行 `bash deployment/build_engine.sh`；启动阶段不再自动导出。旧 engine 经人工确认参数匹配后使用 `--adopt-existing`，需要重建则使用 `--force`。
6. 执行 `bash deployment/run_soccer.sh`，用 Ctrl+C 停止。

三个构建/运行脚本统一使用 `deployment/common.sh`。默认 ROS 发行版为 Foxy；
使用其他已验证环境时设置 `SOCCER_ROS_DISTRO`，安装时同时传入相应 `--ros-distro`。
脚本清理继承的 ROS overlay 和动态库路径，依次加载 ROS、项目 `.soccer_perception_env`、本目录安装环境。
项目环境文件应包含目标设备所需的 ZED/CUDA 额外路径。
Jetson 的 CUDA torch 可来自用户 site-packages，因此脚本清除 `PYTHONNOUSERSITE`。

外部 ROS workspace 的构建与直接 launch 方法见根目录 README。
`deployment/` 下的包装脚本面向本目录构建产物；不要与外部 workspace 的安装目录混用。
修改源码或 YAML 后重新构建；engine 应在目标硬件上生成。
PT、ONNX、engine 统一位于 `soccer_perception_ros/models/`，构建/启动脚本使用同一 `SOCCER_MODEL_DIR`。
首次升级时 `build_project.sh` 会复制旧安装目录中独有的模型；同名不同内容时停止，要求人工选择，绝不覆盖。
迁移后旧安装副本保留但不再使用。外部 workspace 的旧模型可手动运行：

```bash
python3 deployment/migrate_models.py \
  --source /path/to/ros2_ws/install/soccer_perception_ros/share/soccer_perception_ros/models \
  --destination /path/to/project/soccer_perception_ros/models
```

安装产物脱离源码部署时，显式设置 `SOCCER_MODEL_DIR` 为已有模型目录的绝对路径。
构建记录校验权重、参数和 engine 内容；不代替目标设备的 TensorRT 兼容性验证。

## 旧入口迁移

旧根目录的四个 Shell 脚本均已移至 `deployment/`，不保留旧入口。
更新 systemd 的 `ExecStart`、状态机脚本和个人命令中的路径，例如
`/path/to/project/run_soccer.sh` 改为 `/path/to/project/deployment/run_soccer.sh`。
项目根目录、环境文件、模型位置及构建产物位置均保持原位。
