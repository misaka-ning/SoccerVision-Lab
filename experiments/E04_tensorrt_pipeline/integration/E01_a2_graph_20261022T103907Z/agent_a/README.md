# 机器人第一人称足球定位

运行链路：**ZED 双目图像 → YOLO / TensorRT → 候选匹配 → 双目三角化 → 跟踪 → ROS2**。

输出是相机 FLU 坐标，单位米：`x` 向前、`y` 向左、`z` 向上。Viser 网页可视化可选，默认关闭。模型与原有定位阈值保持不变。

## 项目结构

```text
soccer_backend_TensorRT/
├── README.md
├── deployment/                    # 安装、构建与启动入口
│   ├── common.sh                  # 公共环境加载
│   ├── dependencies.sh            # 平台依赖策略
│   ├── setup_dependencies.sh
│   ├── build_project.sh
│   ├── build_engine.sh
│   └── run_soccer.sh
├── requirements/
│   ├── common.txt                 # 公共部署依赖
│   └── test.txt                   # 独立无硬件测试环境
├── .soccer_perception_env.example
├── docs/
│   ├── deployment_jetson.md        # 部署步骤与环境约束
│   ├── development.md              # 开发、测试与交付约定
│   └── maintenance.md             # 历史迁移与验证记录
└── soccer_perception_ros/         # 可独立放入 ROS workspace 的完整 ROS2 包
    ├── CMakeLists.txt
    ├── package.xml
    ├── config/                   # 按职责拆分的配置
    │   ├── camera_deploy.yaml    # 统一入口：列出以下六份参数文件
    │   ├── camera.yaml           # ZED 采集与图像设置
    │   ├── detector.yaml         # YOLO / TensorRT / 推理设备
    │   ├── stereo.yaml           # 双目匹配、候选筛选与定位约束
    │   ├── tracking.yaml         # 跟踪与短时漏检容错
    │   ├── visualization.yaml    # Viser 与可视化点云
    │   └── ros.yaml              # 话题、坐标系名称与输出策略
    ├── launch/                   # 唯一启动流程
    ├── scripts/                  # ROS 节点可执行入口
    ├── models/                   # 唯一模型目录：PT / ONNX / engine / 构建记录
    ├── soccer_perception/        # 安装到 Python site-packages 的代码包
    │   ├── pipeline.py           # 感知流程编排
    │   ├── types.py              # 数据类型，配置字段无默认值
    │   ├── resources.py          # 源码/安装资源路径解析
    │   ├── core/                 # 候选匹配、几何、定位、坐标转换、跟踪
    │   ├── adapters/             # ZED / YOLO / Viser 适配
    │   └── ros/                  # 节点循环、参数读取与消息输出
    └── tests/                    # 无硬件回归与接口测试
        └── fixtures/             # 重构前固定序列基线
```

依赖方向是 `ros → pipeline → core / adapters`，共用数据定义在 `types.py`。算法不导入 ROS；相机、模型和可视化依赖仍延迟加载。测试不混入运行代码，也不随 Python 包安装。

CMake 使用标准 `ament_cmake_python` 安装代码，资源安装到 `share/soccer_perception_ros`。已移除旧 `project/` 目录及手动搜索目录、修改 `sys.path`、切换工作目录的启动逻辑。

## 仓库与部署约定

所有部署脚本及共享逻辑集中在 `deployment/`。从旧版本迁移时，将机器人服务中的脚本路径更新为 `deployment/` 下的新路径。

模型获取和校验见 `soccer_perception_ros/models/README.md`。导出前必须恢复真实模型；导出器拒绝缺失、空文件和 Git LFS 指针。ROS 包构建不复制或生成模型。

在本目录构建和部署可执行：

```bash
bash deployment/setup_dependencies.sh --check-only
bash deployment/build_project.sh
bash deployment/build_engine.sh
bash deployment/run_soccer.sh
```

依赖缺失时先按下节安装。`deployment/build_engine.sh` 需要目标 GPU 环境；已有可用 engine 时可跳过。
详细步骤见 `docs/deployment_jetson.md`，开发与交付说明见 `docs/development.md`。

## 环境安装

在本 README 所在目录执行。沿用原项目的软件栈与版本约束，默认 ROS2 Foxy / Python 3.8；ZED SDK、NVIDIA 驱动与 CUDA 需与目标设备匹配。脚本保留 Jetson 和 x86 两套安装适配，不自动升级部署栈。

```bash
bash deployment/setup_dependencies.sh --check-only
bash deployment/setup_dependencies.sh
```

指定已有解释器、ROS 版本或启用可选 Viser：

```bash
bash deployment/setup_dependencies.sh --python /absolute/path/to/python --ros-distro foxy
bash deployment/setup_dependencies.sh --with-viser
```

Viser 默认不安装、不检查。安装脚本生成本地 `.soccer_perception_env`，用于设置 Python 和 ZED 库路径；在启动前手动 source，该文件不应随项目分发。也可参考 `.soccer_perception_env.example` 手动配置。

## 统一 ROS2 启动流程

节点统一由 `ros2 launch soccer_perception_ros soccer_perception.launch.py` 启动。`deployment/run_soccer.sh` 是加载部署环境并调用该命令的包装脚本。`scripts/soccer_perception_ros_node.py` 是 launch 调用的节点程序，无需单独运行。

配置位于 `soccer_perception_ros/config/`。`camera_deploy.yaml` 只保存 `config_files` 清单，具体参数按职责编辑：

| 文件 | 修改内容 |
| --- | --- |
| `camera.yaml` | ZED 分辨率、打开重试、曝光等图像设置 |
| `detector.yaml` | YOLO 权重、类别、阈值、输入尺寸、设备、TensorRT 与 cuDNN |
| `stereo.yaml` | 双目匹配阈值、候选评分及定位约束 |
| `tracking.yaml` | 跟踪预测、速度衰减与短时漏检容错 |
| `visualization.yaml` | Viser、画面和点云显示；SDK 深度仅用于可视化 |
| `ros.yaml` | 话题、坐标系名称、发布开关与统一输出频率 |

launch 和节点使用同一个清单解析入口。文件路径相对于清单所在目录；每份参数文件保留 `soccer_perception_ros → ros__parameters` 的 ROS 参数结构，不能把清单本身作为 ROS 参数文件传给节点。同一参数只能定义一次，文件内或跨文件重复都会报错，不依赖文件顺序覆盖。缺少文件、清单格式错误，以及合并后缺少必需字段或出现未知字段也会报错。所有配置值仍来自 YAML，Python 不保存另一套默认值；ROS 参数覆盖仅影响本次运行。

将 `soccer_perception_ros/` 放在 ROS workspace 的 `src/` 下即可；它已经包含代码、模型、配置和启动文件，不再依赖旁边的目录。也可将整个仓库放入 `src/`，colcon 会发现其中的 ROS 包。

从旧目录结构迁移时，使用新的 workspace 构建目录，避免旧安装文件被误加载。首次构建，或修改代码 / YAML 后：

```bash
source /opt/ros/foxy/setup.bash
cd /path/to/ros2_ws
colcon build --packages-select soccer_perception_ros
```

每次打开新终端启动时：

```bash
source /opt/ros/foxy/setup.bash
source /path/to/project/.soccer_perception_env
source /path/to/ros2_ws/install/setup.bash
ros2 launch soccer_perception_ros soccer_perception.launch.py
```

将路径替换为实际位置，ROS 发行版不是 Foxy 时替换相应目录。没有生成环境文件时，先按安装章节完成环境配置。`SOCCER_PERCEPTION_PYTHON` 指定节点使用的 Python 绝对路径，节点不再搜索特定用户的 Conda 目录。退出使用 `Ctrl+C`。

安装规则包含后端 Python 包、launch 和整个 `config/` 目录，以及指向源码模型目录的路径记录；不再安装模型副本。修改源码中的 Python / YAML 后重新运行 `colcon build` 更新安装副本。

模型统一存放在源码侧 `soccer_perception_ros/models/`，PT、生成的 ONNX、engine 和 `.engine.json` 构建记录都在这里。YAML 中的 `models/yolo26s.pt` 和 `models/yolo26s.engine` 始终指向该目录，与工作目录和是否通过 `install/` 启动无关。绝对路径及 `~/` 仍支持；自定义 engine 绝对路径时，ONNX 留在 PT 旁边。

部署脚本设置 `SOCCER_MODEL_DIR`；直接 `ros2 launch` 则读取构建时记录的源码模型目录。复制安装产物到另一台机器时，须显式设置 `SOCCER_MODEL_DIR=/absolute/path/to/models`，不会自动回退到 `install/models`。外部 workspace 也遵循这项规则。

正常启动只加载 engine，不自动导出。模型生成明确执行：

```bash
bash deployment/build_engine.sh                  # 首次生成；权重及参数匹配时直接复用
bash deployment/build_engine.sh --force          # 明确重建并替换已有 ONNX / engine
bash deployment/build_engine.sh --adopt-existing # 仅用于已人工确认权重/参数匹配的旧 engine
```

导出会校验权重哈希、输入尺寸、batch、精度请求、动态输入设置和 engine 内容；不匹配时提示明确重建，不会悄悄覆盖。旧 engine 没有构建记录，须人工确认后采用或重新生成。`--adopt-existing` 记录当前配置，不能自动证明旧 engine 的实际参数。显式将 `yolo_model` 配为 `.engine` 时支持无 PT 加载，仅检查文件非空；TensorRT 环境兼容性仍需在目标设备验证。

`build_project.sh` 首先将旧 `install/.../models/` 中缺少的文件复制回统一目录；同名不同内容则停止并报告冲突，保留两边文件。旧安装副本不自动删除，也不再作为运行数据源。已有 ONNX 与新导出内容不同时，需用 `--force` 明确替换。

## 模型与常用参数

| 参数 | 用途 |
| --- | --- |
| `yolo_model` | PT、ONNX 或已有 TensorRT engine 的路径 |
| `yolo_tensorrt` | 从 PT 导出并使用 engine |
| `yolo_engine_path` | engine 加载 / 导出路径 |
| `yolo_trt_batch` | 双目批处理容量，当前配置为 2 |
| `imgsz`、`det_conf`、`yolo_class_ids` | 检测输入尺寸、置信度和类别 |
| `zed_resolution` | 相机分辨率，采集帧率由 SDK 自动选择 |
| `max_coast_frames`、`max_coast_time_s` | 失球后短时预测边界 |
| `deploy_packet_rate_hz` | 唯一输出频率，必须为正数，当前配置为 15 Hz |
| `deploy_send_invalid_state` | 是否发布完整无效状态 JSON |

TensorRT 导出逻辑和兼容处理沿用原实现，首次导出需要目标机器的 GPU 环境。不要假设不同机器、CUDA 或 TensorRT 版本的 engine 可以互换。已有 engine 可直接设为 `yolo_model`。ONNX 文件继续保留，但不用于替换默认 PT 模型。

只需在 `config/ros.yaml` 中设置 `deploy_packet_rate_hz: 10`，ROS 节点就按 100 ms 的固定周期发布新结果，Viser 随同更新。等待时间扣除采集、推理与发布耗时，避免按帧丢弃造成频率折半，也避免每轮固定 sleep 导致频率偏低。相机采集帧率在 `soccer_perception_ros/config/camera.yaml` 中通过 `zed_fps` 设置，当前为 `100`（ZED Mini、VGA）；`0` 表示 SDK 自动选择，不保证最高帧率。启动日志分别显示请求帧率和实际打开帧率。采集帧率与 `deploy_packet_rate_hz` 独立，实际新结果输出还受处理速度限制。已删除 `zed_viser_update_rate_hz`、`real_time` 和 `real_time_factor` 配置。

算力不足时按实际处理速度输出，不重复旧结果，也不突发补发。状态话题的 `output_rate_hz` 显示最近约 5 秒的实际输出频率（首条为 0，之后逐步形成统计）。可以用 `ros2 topic hz /soccer_perception/ball_valid` 检查接收频率；无有效球时 position 话题仍遵守原有发布开关，可能停止发布。

### Viser

`zed_depth_mode` 位于 `config/visualization.yaml`，只控制显示用的 SDK 深度。已删除的五点深度定位、点云裁剪与球拟合没有恢复。

需要 Viser 网页可视化时，先在机器人项目根目录运行以下命令，将可视化依赖安装到运行环境：

```bash
bash deployment/setup_dependencies.sh --with-viser
```

默认运行 `bash deployment/setup_dependencies.sh` 不安装 Viser。仅设置 `zed_viser_enabled: true` 不会自动安装依赖；未安装时节点会报 `No module named 'viser'` 并退出。

安装完成后，在 `soccer_perception_ros/config/visualization.yaml` 的 `ros__parameters` 下配置：

```yaml
zed_viser_enabled: true
zed_viser_show_point_cloud: true
zed_depth_mode: QUALITY
```

修改源码配置后，重新构建并启动节点：

```bash
bash deployment/build_project.sh
bash deployment/run_soccer.sh
```

浏览器访问 `http://机器人IP:8080`，查看左目画面、点云和球位置。点云与检测复用同一次相机 grab，不启动第二个相机进程。

关闭 Viser 或关闭其点云功能时，不计算 SDK 深度、不提取点云。`zed_depth_mode: NONE` 时仍可显示画面和球标记，但不显示点云。SDK 深度只用于显示，不参与球的位置计算。

## ROS 接口

| Topic | 消息类型 | 内容 |
| --- | --- | --- |
| `/ball_position` | `geometry_msgs/PointStamped` | 相机 FLU 球坐标 |
| `/soccer_perception/ball_valid` | `std_msgs/Bool` | 跟踪结果有效性 |
| `/soccer_perception/ball_status` | `std_msgs/String` | 状态 diagnostics JSON |
| `/soccer_perception/ball_position_camera_json` | `std_msgs/String` | 可选位置 JSON |

球位置话题默认配置为相对名 `ball_position`，根命名空间下解析为 `/ball_position`。AMP/BFM 默认使用同名输入；使用 ROS namespace 时，发布端与消费端需处于相同命名空间。

`frame_id` 默认 `camera_flu`，改名不会改变坐标轴。位置 JSON 保留七字段：

```json
{"type":"ball_position_camera","timestamp":1.25,"valid":true,"confidence":1.0,"x_m":2.5,"y_m":-0.25,"z_m":0.1}
```

短时预测仍按原有策略提供有效跟踪位置。跟踪失效后，`valid=false`、`confidence=0`、坐标为 `null`。默认不发布无效 `PointStamped`；`publish_invalid_position=true` 时沿用零坐标发布语义，接收方应同时检查有效性。

`deploy_send_invalid_state=false` 时，无效帧只发布限频后的 valid/status，不发布位置 JSON。`publish_json=false` 可关闭 JSON topic。状态保留跟踪、测量有效性和候选选择诊断，删除点云裁剪及已移除算法的 diagnostics。

```bash
ros2 topic echo /soccer_perception/ball_status
ros2 topic echo /ball_position
```

## 测试与实机自检

无硬件测试只需要 NumPy、PyYAML 和 OpenCV，不需要 ROS、ZED、Ultralytics 或 Viser：

```bash
cd soccer_perception_ros
python3 -m unittest discover -s tests -t . -v
```

ROS workspace 中也可执行已注册的 CMake 测试：

```bash
colcon test --packages-select soccer_perception_ros
colcon test-result --verbose
```

测试使用构建时的 Python，需要该解释器具备 NumPy、PyYAML、OpenCV。

实机使用同一条 `ros2 launch` 命令启动，持续处理相机输入，检查完成后按 `Ctrl+C` 停止。程序没有按处理帧数自动停止的配置。相机故障仍会报错退出。

检查 topic、连续跟踪、遮挡后恢复、Viser 开关及退出后的相机释放。相机抓取失败会报错退出并释放资源，避免在失联后无限循环。

历史无硬件验证结果与瘦身清单见 `docs/maintenance.md`。已移除的 TCP/Qt、五点深度、点云测距、ROI 和防抖入口及参数不再兼容。
