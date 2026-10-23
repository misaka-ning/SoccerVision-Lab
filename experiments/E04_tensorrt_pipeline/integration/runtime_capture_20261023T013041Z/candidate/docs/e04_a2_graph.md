# E01 的 A2 + CUDA Graph 接入

常规 ROS 感知节点通过 `PipelineFactory → YoloBallDetector` 使用 E04 的 A2 与 Graph。默认配置使用机器人已经存在的 E01 Engine，不导出模型、不训练、不改网络。E02 文件保留。

## 配置与启动

编辑 `soccer_perception_ros/config/detector.yaml`：

```yaml
yolo_model: models/E01_baseline.engine
yolo_engine_path: models/E01_baseline.engine
yolo_optimization: "a2_graph"
```

这些字段放在原有 `soccer_perception_ros: ros__parameters:` 下。默认使用 E01 的 class0、conf0.45、top-k5、640、静态 batch2；NMS IoU 和原有 NMS 调用保留。Graph 针对 TensorRT 8.5 和 `[2,3,640,640]` FP32 输入、`[2,5,8400]` FP32 输出，使用 Engine 既有 FP16 tactics。显式 `.engine` 路径直接加载现有文件，无需 PT 的构建 sidecar。

机器人首次接入已执行项目构建并更新安装副本。正常启动仍使用：

```bash
bash /home/nvidia/soccer_backend_tensorrt/deployment/run_soccer.sh
```

后续修改源码或 YAML 时，先执行 `deployment/build_project.sh`，再重启感知节点。这里只需构建 ROS 包，不要为切换 A2/Graph 执行 `build_engine.sh`。本地没有该 E01 Engine 时不能直接进行真实推理，应在机器人使用已有 Engine。

## 启用状态

默认 `a2_graph` 在**每次启动、正式推理开始前**自动捕获一次 Graph；模型没有变化也会重新捕获。重新加载模型时先释放旧 Graph，再为本次模型创建和捕获新 Graph。捕获只在当前感知进程内有效，不保存成跨进程缓存。`build_project.sh` 只构建和测试，不负责捕获；日常仍通过 `run_soccer.sh` 启动。

模型加载时先丢弃一次原路径初始化结果，安装优化，再丢弃一次捕获/预热结果并等待完成。启动画面不进入检测输出、双目定位和 ROS 发布。随后每次推理更新当前左右目输入后 Replay；Graph 输出独立复制，避免后续帧覆盖已返回的结果。

启动日志包含 `E04 optimization initialized:` JSON。核对 `mode=a2_graph`，`state.components.engine.effective=graph`、`capture_count=1`、`fallback_count=0`，以及后处理组件 `effective=a2`。业务运行时可调用 `detector.optimization_status()` 查看 Replay 计数。仅配置名或 `enabled=true` 不能证明 Graph 捕获成功。

捕获不兼容或可恢复失败会走原推理路径，输出一次 `E04 optimization fallback` 告警并保留原因/计数。无法安全恢复的 CUDA 清理错误会抛出并拒绝该帧。退出先撤销本实例的 hook、同步并释放私有资源；失败保留 handle 供重试。

A2 保留原来的过滤、NMS、框缩放和排序，将左右目最终框合并为一次 CPU 回传，再按原顺序拆回各目。未启用 C2 GPU 预处理、异步流水线或双缓冲。优化模式显式 `rect=False`，保持 E04 的 640 方形 letterbox 契约。

## 开关与回滚

| `yolo_optimization` | 行为 |
| --- | --- |
| `none` | 原检测执行路径，保留所选 E01 Engine |
| `a2` | 仅合并最终检测框回传 |
| `graph` | 仅 CUDA Graph |
| `a2_graph` | A2 + Graph，当前默认 |

修改后构建、重启生效；运行中的 `ros2 param set` 不会重新安装 backend。`none` 不会换回 E02，也不修改相机、定位、跟踪或 ROS 协议。

旧实验环境变量 `SOCCER_YOLO_POSTPROCESS`、`SOCCER_YOLO_NMS`、`SOCCER_YOLO_PREPROCESS` 若分别不为默认 `baseline/torch/baseline`，会在加载前报错，避免两套 hook 叠加。清除这些旧变量后使用新的 YAML 开关。

## 验证边界

本次接入复用 E04 已验证的 Graph/Postprocess 核心，新增正常节点的配置和生命周期接线。CPU/mock 测试及固定 Val Golden 对照覆盖数值、顺序、每目归属和下游协议；这不代替在机器人启动后的 CUDA 状态确认。接入时不自动启动相机或生产感知进程，不恢复已暂停的长测。

E04 组合实验得到的约 6.93% Hz 收益属于当时的交错 A/B 场景，不是本次接入后重新测得的生产收益。长时间稳定性 B5、真实三维精度和新生产场景性能仍需单独验证。ROS 发布上限维持设备原配置，不能把它当作处理吞吐率。
