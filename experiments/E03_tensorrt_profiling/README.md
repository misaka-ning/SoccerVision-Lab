# E03：TensorRT 性能剖析

实验定义与验收见 [PLAN.md](PLAN.md)。运行 `20261021T080741Z_824b47` **已完成测量、完整原始文件回收、625 项 SHA256 校验与本机 CPU 分析**。结论见 [REPORT.md](REPORT.md)，四份 Top20 与新 detailed 实际 tensor/tactic 见 [TOP20.md](results/TOP20.md)，其他产物见 [结果索引](results/README.md)。原始记录保留在机器人同名 run 与本机忽略的 `runs/` 中。

## 执行位置

TensorRT 构建、正确性验证、正常测速和 Nsight 采集均在 `nvidia@192.168.98.248` 上执行。远端运行目录为：

```text
/home/nvidia/soccer_backend_tensorrt/results/E03_tensorrt_profiling/20261021T080741Z_824b47
```

使用机器人现有部署环境，先在其项目根目录加载 `deployment/common.sh` 和 `soccer_load_runtime yes`。机器人系统 Python 与部署 Python 版本不同，不应混用。密码不写入命令文件或配置。

## 脚本职责

- `execute_robot.py`：串行构建独立 FP16 performance/profile Engine；复用现有 Engine 读取器检查 64 张固定 Val 输入，冻结数值与检测一致性阈值。
- `collect_robot.py`：等待构建完成，正确性通过后复用机器人既有测速工具，完成 performance 版三轮正常计时、详细版一轮正常校核、A～C checkpoint、三次逐层 profile 和 E01 传输/Graph 对照。
- `collect_legacy_robot.py`：等待主采集结束后，直接剖析原有 Engine 的冻结序列化副本，每模型三次；不将重建 Engine 的耗时冒充旧 Engine 结果。
- `trace_robot.py`：预热结束后显式调用 CUDA Profiler API；用 NVTX 标记稳态窗口和逐次推理，为捕获范围验收提供直接证据。
- `trace_detector_robot.py`：使用固定 Val 左右图复用安装版检测器，分别记录预处理、推理、后处理与候选转 CPU；不启动相机、ROS 或可视化。
- `analyze.py`：在本机通过 CPU 处理原始计时、融合层归因和 Nsight SQLite；计算区间并集，避免将重叠工作直接相加。

各脚本的参数可通过 `--help` 查看。构建与采集脚本应只用于独占的新 run；日志与产物不覆盖已有文件。它们不修改生产 Engine、不调整功耗或时钟，也不停止其他机器人程序。

## 分析复现

原始结果已回收，使用带 NumPy 的本机解释器可重算：

```bash
/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python \
  /home/misaka/workspace/experiments/E03_tensorrt_profiling/analyze.py \
  --run /home/misaka/workspace/experiments/E03_tensorrt_profiling/runs/20261021T080741Z_824b47
```

`analysis/` 下生成正常计时表、每层和 Top 20 CSV、模块汇总及已提供 trace 的工作/间隔/API 分析。Engine 百分比以同一次 profile 的层时间总和为分母；不将其视作无 profiler 整网延迟的精确分解。互斥表中，L10 C2PSA 从 Backbone 扣除，L22 内 PSA 从 Neck 扣除，二者计入 Attention；跨模块/子模块融合和未归因部分单列。另保留结构视角，不能将两种视角的成本相加。

run 内保留 source 快照与 hash、原始模型指纹、运行时有效参数、完整命令与退出状态。历史系统结果仅在 Engine hash 核验后作为历史证据引用，不冒充本次重新运行。

`MEASUREMENT_SUMMARY.json` 已根据回收原始分析核对并补齐，保留来源、统计口径与归档校验信息。`publish_summary.py` 从它生成小型 CSV、PNG/PDF；它不代替原始逐层数据。回收记录见 [RECOVERY.md](RECOVERY.md)，原始机器人分析另存 `analysis_robot_snapshot/`。
