# E01 A2+Graph 正常感知链路接入记录

日期：2026-10-22。接入 ID：`E01_a2_graph_20261022T103907Z`。

## 结果

已接入本地实际项目 `/home/misaka/soccer_backend_tensorrt`，并同步、构建到机器人 `/home/nvidia/soccer_backend_tensorrt`。安装目录和源码逐文件 hash 核对通过。默认检测配置现为 E01 现有 Engine + `yolo_optimization: a2_graph`。未启动相机、生产感知节点或 GPU benchmark；既有长测暂停状态保持，启动后的真实 CUDA 捕获尚未在本次执行中验证。

机器人核对前用户配置已由早期 E02 临时默认切回 `E01_baseline.pt` / `E01_baseline.engine`；本次改为显式 `.engine` 加载，以复用已有设备 Engine，避免依赖不存在的 PT `.engine.json` sidecar。没有生成 sidecar 或改写模型。

## 配置与行为

- E01 FP16 tactics，静态 batch2 / 640；FP32 输入 `[2,3,640,640]`，FP32 输出 `[2,5,8400]`。
- class0、conf0.45、top-k5、外部原 NMS 不变。双目顺序、定位、跟踪及 ROS 协议未改。
- 新开关：`none/a2/graph/a2_graph`。关闭仅恢复原执行路径，保留 E01。
- Graph/Postprocess 核心直接取 E04 已验证 R4 源码。Graph SHA256：`85aee1a4427bb6c558273f87d34a6a349a148a7b2f0b4b97b7d6ab190ad6f695`。
- 启动丢弃一次原预测初始化及一次优化捕获结果；正式帧持续更新左右目图像。Graph 私有缓冲和输出生命周期沿用已验实现。
- 捕获回退和异常可观察；正常退出/重新加载撤销 hook，清理失败保留 handle 以便重试。CPU 方法没有新增每帧 CUDA 同步。
- 保留本地已有实验 predictor 支持；新开关与非默认旧实验环境变量互斥，避免 FastDetectionResult 或预处理 hook 叠加。
- 机器人原 ROS 发布上限 50Hz，本地原 15Hz，各自保持。不同设备配置没有整目录互相覆盖。C2、异步流水线、双缓冲没有启用。

## 检查与测试

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 独立副本 CPU/mock 全套，含 61 对 Val Golden | 163 项，160 通过、3 跳过 | `project/cpu_tests_with_golden.log` |
| 机器人 colcon 构建与 CPU 回归，CUDA_VISIBLE_DEVICES 置空 | 163 项，159 通过、4 跳过，0 失败 | `robot_validation/build_test.log` |
| Graph 19 项 CPU/mock 与生命周期审查 | 通过；核心字节未变 | `tests/test_e04_graph.py` 与 manifest |
| Golden 最终候选及真实下游定位/跟踪/ROS 计算 | 61 对 Val 对照通过；未访问 Test | `test_e04_postprocess.GoldenTests` |
| 安装包及全部 YAML 与源码 hash | 一致，默认 E01+a2_graph | `robot_validation/verification.json` |
| 本地其他已快照文件 | 与修改前 hash 一致 | `before_manifest.json`、`local_changes.json` |
| E01 权重/Engine hash | 修改前后一致 | `robot_validation/applied.json`、`verification.json` |
| 本次生产捕获、性能与长时稳定性 | 未运行 | 不将 CPU/mock 作为 CUDA 性能结论 |

跳过项：屏蔽 GPU 后的两个 CUDA 专用测试、未提供 E02 专用图片的旧预处理测试；机器人另跳过 torchvision C++ NMS probe（原 ABI/ops 缺失）。A2 沿用原纯 Torch NMS，未安装或升级 Torch/Torchvision/CUDA。colcon 外层 `0 skipped` 是测试容器口径，内部实际4项跳过，以 unittest 日志为准。

Golden 检查重放保存的最终框并对比候选、定位、跟踪和 ROS 序列；本次没有重新运行 GPU 模型预测。图像变化正确性仍引用 E04 既有实机验证，完整系统新生产场景性能与 B5 长时间稳定性未补测。

## 原始模型与版本保护

原 Git 分支 `dev`，HEAD `5ef358e9b7df2edcf36d4618d3e2b6aad70e0812`；接入前两端都有未提交改动。本次未 commit/push、未重置用户改动。

E01 Engine SHA256：`98c1b6bc703b29874d95db94d9cf51ef5b4a4142a7ca6cf22362a0c616fbf348`。

E01 PT SHA256：`285c198aff043fe7e7486515dbdc1a2cc02db5daf9a0f55f8ce3c6cabf2743ac`。

E02/E03 历史数据未覆盖；未改网络、输入尺寸、功耗模式、GPU 时钟或其他后台进程。源码变化由 dirty HEAD 加文件 manifest 共同标识，不能只用 HEAD 代表本次交付。

## 启动与确认

机器人构建安装已完成。用户在正常安全运行条件下启动：

```bash
bash /home/nvidia/soccer_backend_tensorrt/deployment/run_soccer.sh
```

日志 `E04 optimization initialized:` 的 `mode` 应为 `a2_graph`，`state.components.engine.effective` 为 `graph`、`capture_count=1`、`fallback_count=0`，postprocess `effective=a2`。若输出 fallback 告警，实际走原路径，应按 JSON 中的原因调查，不算作 Graph 生效或已获得提速。

E04 历史交错实验 R0→R4 约+6.93% processing Hz 属于当时场景；本次没有重新测量生产 Hz，因此不承诺启动后达到固定频率。发布 Hz 还受配置上限限制。

## 回滚

编辑机器人源码 `soccer_perception_ros/config/detector.yaml`，将 `yolo_optimization` 改为 `"none"`，运行 `deployment/build_project.sh` 后重新启动节点，即可保留 E01 恢复原执行路径。不是运行中的热切换；不要只用 `ros2 param set` 判断已切回。

本地原文件备份：本记录同目录 `local_backup/`；机器人原文件和安装代码/配置备份：`/home/nvidia/soccer_backend_tensorrt/results/E04_tensorrt_pipeline/integration/E01_a2_graph_20261022T103907Z/backup/`。完整撤销时按 manifest 恢复原文件、仅删除 manifest 中原先不存在且未再修改的新文件，再重建 ROS 包。不要恢复或删除 models/。

## 文件清单

本地仅应用18份新增/修改文件；机器人27份，额外9份为本地此前已有的兼容 predictor 依赖及对应测试/fixture，默认关闭，未叠加运行。完整哈希见 `local_changes.json` 和 `robot_changes.json`。核心接线为：

- `soccer_perception_ros/config/detector.yaml`
- `soccer_perception_ros/soccer_perception/adapters/yolo.py`
- `soccer_perception_ros/soccer_perception/pipeline.py`
- `soccer_perception_ros/soccer_perception/ros/node.py`
- `soccer_perception_ros/soccer_perception/types.py`
- `soccer_perception_ros/soccer_perception/optimizations/__init__.py`
- `docs/e04_a2_graph.md`
