# 项目结构与维护记录

> 本文为历史记录；当前目录和启动方式以根目录 README 为准。
> 旧版删除 Shell 入口的记录不适用于现有部署包装脚本。个人备份不属于仓库交付内容。

## 删除外部控制器联动测试（2026-10-15）

已删除 `tests/test_short_loss_tolerance.py`。该文件混合视觉与控制器行为测试，
通过固定的 `workspace_xuning/ros2/src/instinct_onboard/scripts` 路径导入仓库外的
`auto_soccer_controller`，导致独立部署时无法完成测试发现。
同时移除其他测试对该文件的说明引用。其余测试不导入该控制器，
仅验证本项目的视觉感知、配置、ROS 接口及资源生命周期。
下方缺少外部控制器的失败记录保留为历史说明。

## 配置按职责拆分（2026-10-15）

`config/camera_deploy.yaml` 现为 `config_files` 清单，原有 78 个参数拆入
`camera.yaml`、`detector.yaml`、`stereo.yaml`、`tracking.yaml`、
`visualization.yaml` 和 `ros.yaml`，参数值与类型保持不变。
launch 与节点共用 `resources.py` 的清单解析逻辑，文件内或跨文件重复参数会报错，
节点继续检查合并后的必需字段、未知字段及参数类型。下面“唯一配置文件”的表述为历史记录。

本次验证：拆分前后 78 个参数的值与类型一致，62 项无硬件测试通过（含新增的
10 项配置清单与加载测试）。完整发现测试时，`test_short_loss_tolerance.py` 因缺少
仓库外的 `auto_soccer_controller` 无法导入；未修改该外部依赖，也未进行 ROS/相机实机验收。

## 配置清理：持续运行与 Viser 深度用途

删除 `max_frames` YAML 项、运行时字段和 pipeline 帧数计数/停止分支；实机持续处理输入，直到 ROS 停止或发生故障。删除无代码读取的 `candidate_selector` 参数，候选匹配仍固定使用双目方案。

`zed_depth_mode` 保留用于已确认保留的 Viser 点云显示，移至 YAML 可视化分组，注明只有可视化和点云显示同时开启才生效。球定位不读取 SDK 深度，五点深度、裁剪及球拟合未恢复。其他参数值不变。

## 目录重组：完整 ROS2 包与分层 Python 包

### 结构与路径变化

- 后端统一迁入 `soccer_perception_ros/soccer_perception/`，Python 导入名为 `soccer_perception`；旧 `project/` 删除，不保留重定向或兼容空壳。
- `core/` 保存几何、匹配、定位、跟踪；`adapters/` 保存 ZED、YOLO、Viser；`ros/` 保存 ROS 节点和输出；`pipeline.py` 编排流程。
- 数据模型由 `models.py` 改为 `types.py`，避免与模型权重目录混淆；`BackendConfig` 仍只有类型定义，唯一配置仍是 `config/camera_deploy.yaml`。
- 只供 ROS 输出使用的接口常量合并入 `ros/output.py`；测试搬到包根 `tests/`，序列数据进入 `tests/fixtures/`。
- PT/ONNX 移至 ROS 包内 `models/`，内容和 SHA-256 未变。YAML 仅调整模型及 engine 的相对路径为 `models/...`，其余值保持不变。
- 节点入口不再搜索目录、修改 `sys.path` 或调用 `chdir`。`resources.py` 在源码模式识别确定的包边界，在安装模式使用 ament 索引，模型路径解析为绝对路径。
- CMake 改用 `ament_python_install_package(soccer_perception)`，代码安装到 Python 包目录，launch/config/models 安装到包 share 目录；不再访问 `../project` 或包外模型。engine 按目标设备生成，不随安装分发。
- `package.xml`、安装脚本、测试导入和 README 同步更新。维护历史移至本文，README 保留当前结构及运行说明。

安装方式依据 [ament_cmake_python 官方说明](https://docs.ros.org/en/jazzy/p/ament_cmake_python/__README.html)，并核对了 Foxy 对应的安装宏；测试使用 [Foxy 官方 ament_add_test 宏](https://github.com/ament/ament_cmake/blob/foxy/ament_cmake_test/cmake/ament_add_test.cmake)。

### 验证与边界

- 迁移前 39 个测试通过；迁移后 **43 个测试通过**，新增源码/安装资源解析、工作目录无关性及节点入口导入检查。
- 49 帧固定序列回归通过。核心算法、pipeline、ZED、Viser 和数据类型的 AST 去掉导入后与迁移前一致。
- Python 3.8 语法、安装 Shell 语法与 help 检查通过；运行代码无旧包导入或兄弟目录依赖。
- 项目外隔离目录使用**未修改的 ROS Foxy Python 安装宏、测试宏与测试运行器**，执行 CMake configure/build/install/CTest 成功。仅 ament 包发现/注册环境为模拟；没有宣称完成真实 ROS 构建。
- 安装后的全模块导入通过，并使用**真实 ament_index_python** 在任意工作目录下解析安装 YAML 和模型。测试不会随运行 Python 包安装。
- 本机缺少 ROS2/ZED 实机环境，真实 colcon workspace、ROS graph、GPU/TensorRT 和相机仍需目标设备验收。

启动命令保持 `ros2 launch soccer_perception_ros soccer_perception.launch.py`。首次迁移请使用新的 workspace 构建目录，避免加载旧安装残留；此后修改源码 YAML 仍需重新构建以更新安装副本。

迁移前完整备份：`/path/to/local-backups/layout_20260928_173236/before.tar.gz`。该目录保存模型校验及 `cmake-check/` 中的隔离验证脚本、安装产物和日志。

以下为之前各阶段的历史记录，其中旧路径只用于记录当时的状态。

## 后续调整：统一 ROS2 启动入口

已删除 Shell 启动入口，统一通过 `ros2 launch soccer_perception_ros soccer_perception.launch.py` 启动。README、安装脚本生成的环境说明及环境示例同步更新；节点程序仍由 launch 调用。启动前显式加载 ROS、Python/ZED 环境文件与 workspace 环境。此次仅调整入口与说明，未修改定位逻辑、launch 节点定义或 YAML 参数。旧入口备份位于 `/path/to/local-backups/ros_launch_only/`。

以下为之前调整的历史记录。

## 后续调整：YAML 为唯一配置来源

已删除 `project/python_backend/config.py`。运行参数与 ROS 话题设置全部从 `soccer_perception_ros/config/camera_deploy.yaml` 读取；`models.py` 的 `BackendConfig` 仅保存字段类型，无默认值。原 YAML 内容未修改。

直接启动和 ROS launch 固定使用这份配置；移除另选 YAML 的环境变量和 launch 参数。ROS `-p` 临时覆盖保留，安装部署使用同一文件的打包副本。源码 YAML 修改后需重新构建安装副本。

缺失文件、缺失字段或未知字段明确报错，不回退到 Python 默认值。相机 `unchanged`、可选负数、模型 Path、布尔值和 ROS 数值转换保留。

39 个无硬件测试通过，含 49 帧原始基线回归、修改 YAML 后即时读取、ROS 临时覆盖、字段缺失、非项目工作目录及可选值转换。Python 3.8 语法和 Shell 语法通过；模拟 ament 安装后的 YAML 寻址与加载通过，尚未进行真实 ROS/ZED 实机验证。

本次调整前备份：`/path/to/local-backups/yaml_only_20260928_171857/before.tar.gz`，同目录保存测试日志。

以下为上一轮瘦身的历史统计与交付记录。

## 结果

| 项目 | 修改前 | 修改后 |
| --- | ---: | ---: |
| 后端运行模块 | 24 | 15 |
| 后端运行 Python 行数（含注释、空行，不含测试） | 7110 | 3017 |
| 全项目 Python 行数（含测试） | 9036 | 4000 |
| BackendConfig 参数 | 139 | 73 |

后端运行代码减少 57.6%。两个模型原样保留，因此项目磁盘占用仍约 57 MB。

保留：ZED 采集、YOLO/TensorRT、候选筛选、双目三角化、跟踪、ROS2、可选 Viser、Jetson/x86 安装适配。候选选择、几何、坐标转换、检测和跟踪五个核心模块与备份逐字节一致；部署 YAML 中所有保留参数的值一致。

新增：独立 ROS 数据/限频模块、ROS 接口和相机生命周期测试、固定序列基线、根目录 README、环境配置示例与忽略规则。ROS 安装规则包含后端与模型；移除硬编码个人环境路径。

## 验证结果

- 修改前原有 61 个测试通过；裁剪后保留 23 个相关测试，新增 11 个测试，总计 **34 个通过**。
- 修改前保存的 49 帧固定序列覆盖连续跟踪、错误匹配、单目漏检、长时失球、恢复；修改后的测量、位置 JSON、速度和跟踪模式逐帧完全一致。
- ROS 消息结构、FLU 坐标、无效位置发布、JSON 开关、状态单独发布、限频、NumPy/NaN/Inf 清洗均通过无硬件测试。
- 可视化关闭不导入 Viser；SDK 深度仅在 Viser 点云开启且深度模式非 NONE 时启用，点云采集为同次 grab 的 XYZRGBA。
- 模型加载失败时关闭 pipeline；相机 grab 失败报错退出并释放资源，取代原来的无限重试。
- Shell 语法、安装脚本 help、Python 3.8 语法解析通过。
- CMake 安装规则及安装目录下入口寻找后端通过模拟 ament 检查；**不等同于真实 colcon 构建**。

测试环境位于项目外 `/path/to/local-backups/test-venv`，使用 Python 3.14、NumPy 2.5.3、PyYAML 6.0.3、OpenCV headless 5.0.0.93。未修改部署环境或安装脚本既有版本约束；Python 3.8 运行时仍需目标设备验收。

当前机器未提供 ROS2、ZED SDK 运行环境，尚未验证真实相机、ROS graph、GPU 推理、TensorRT 导出、Viser 浏览器显示及 Jetson/x86 实机运行。现场使用 README 的启动命令验收这些项目。

## 恢复与模型校验

完整备份：`/path/to/local-backups/20260928_165906/original.tar.gz`。
同目录保存原始文件/行数清单、模型校验、测试日志及完整序列前后输出。原 `.git` 为空，未冒充有效仓库，也未创建提交。

恢复到另一个目录进行检查：

```bash
mkdir -p /path/to/restore
tar -xzf /path/to/local-backups/20260928_165906/original.tar.gz -C /path/to/restore
```

| 模型 | SHA-256（前后相同） |
| --- | --- |
| `yolo26s.onnx` | `d93d91621a80a198a5b7d8c38fd4ce0c6395b69f798855ec10b65933fff943b6` |
| `yolo26s.pt` | `646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b` |

## 删除清单

- `.soccer_perception_env`
- `project/README.zh-CN.md`
- `project/python_backend/cli.py`
- `project/python_backend/communication.py`
- `project/python_backend/docs/python_api.md`
- `project/python_backend/main.py`
- `project/python_backend/pointcloud_crop.py`
- `project/python_backend/pointcloud_sphere_fit.py`
- `project/python_backend/protocol.py`
- `project/python_backend/rendering.py`
- `project/python_backend/roi_detection.py`
- `project/python_backend/stabilization.py`
- `project/python_backend/tcp_server.py`
- `project/python_backend/tests/test_pointcloud_crop.py`
- `project/python_backend/tests/test_pointcloud_sphere_fit.py`
- `project/python_backend/tests/test_zed_five_point_localization.py`
- `project/run_zed_yolo_backend.sh`
- `soccer_perception_TensorRT部署手册.md`
- `soccer_perception_ros/README.md`

另已清除 Python 缓存和原本为空的 `.git`、`.agents`、`.codex` 及清空后的旧文档目录。完整前后测试输出与备份保存在项目外；项目内仅保留回归测试需要的精简基线。

## 参数与接口迁移

删除以下参数，使用本项目精简后的 YAML 替换旧配置；不提供空壳兼容分支。ROS topic、位置 JSON 七字段和坐标语义不变；status 不再包含点云裁剪字段，候选 diagnostics 不再包含 ROI/深度候选子项。

`debug_draw_candidates`、`distance_measurement_mode`、`host`、`include_images`、`jpeg_quality`、`pointcloud_crop_depth_window_m`、`pointcloud_crop_enabled`、`pointcloud_crop_include_debug_samples`、`pointcloud_crop_margin_ratio`、`pointcloud_crop_max_abs_x_m`、`pointcloud_crop_max_abs_y_m`、`pointcloud_crop_max_debug_samples`、`pointcloud_crop_max_depth_m`、`pointcloud_crop_max_downsampled_points`、`pointcloud_crop_max_raw_points`、`pointcloud_crop_min_depth_m`、`pointcloud_crop_min_valid_points`、`pointcloud_crop_observe_only`、`pointcloud_crop_outlier_neighbor_count`、`pointcloud_crop_outlier_std_ratio`、`pointcloud_crop_stride_px`、`pointcloud_crop_voxel_size_m`、`pointcloud_sphere_cluster_radius_m`、`pointcloud_sphere_expected_radius_m`、`pointcloud_sphere_inlier_distance_m`、`pointcloud_sphere_max_cluster_candidates`、`pointcloud_sphere_max_reference_depth_delta_m`、`pointcloud_sphere_max_residual_std_m`、`pointcloud_sphere_min_cluster_points`、`pointcloud_sphere_min_crop_points`、`pointcloud_sphere_min_inlier_ratio`、`pointcloud_sphere_radius_tolerance_ratio`、`port`、`roi_conf`、`roi_disparity_margin_px`、`roi_long_scale`、`roi_long_time_s`、`roi_max_time_s`、`roi_medium_scale`、`roi_min_size_px`、`roi_short_scale`、`roi_short_time_s`、`roi_top_k`、`run_mode`、`stabilizer`、`stabilizer_downscale`、`stabilizer_max_features`、`stabilizer_max_rotation_deg`、`stabilizer_max_translation_px`、`stabilizer_min_inliers`、`stabilizer_smoothing_alpha`、`track_aware_roi`、`zed_coordinate_mapping`、`zed_depth_required`、`zed_five_point_confidence_min`、`zed_five_point_enabled`、`zed_five_point_max_3d_jump_m`、`zed_five_point_max_depth_m`、`zed_five_point_max_depth_std_m`、`zed_five_point_max_lateral_std_m`、`zed_five_point_min_depth_m`、`zed_five_point_min_valid_points`、`zed_five_point_prefer_depth`、`zed_five_point_radius_consistency_enabled`、`zed_five_point_radius_tolerance_ratio`、`zed_five_point_sample_radius_scale`。
