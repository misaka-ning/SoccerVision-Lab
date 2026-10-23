# E03：YOLO26s TensorRT 逐层性能剖析与瓶颈定位

状态：**2026-10-21 已完成，运行 ID 为 `20261021T080741Z_824b47`。最终结果见 [REPORT.md](REPORT.md)，校验与回收记录见 [RECOVERY.md](RECOVERY.md)。以下保留执行前计划，实际完成范围与限制以报告为准。**

本实验以 E01 为主基线、E02 为诊断对照，回答三个问题：当前 Orin 部署的时间花在哪里；第 19 层缩窄为何没有带来可测量加速；下一轮应优先优化哪个模块或系统环节。实验成果是有证据的瓶颈排序和后续实验建议，不以本轮必须提速为完成条件。E03 使用本名称；历史组织草案中的 `E03_p2` 尚未实施，新增 P2 另行编号。

用户提供的历史参考是 E01 双目 batch=2 Engine 约 28 ms、系统约 16.5 Hz；这些数值尚未在 E03 复测。系统目标 30/50 Hz 对应约 33.3/20 ms 的平均每双目帧对处理周期，16.5 Hz 对应约 60.6 ms。它们用于后续预算分析，不代表端到端延迟；不同负载、流水线或时序边界的历史值不能直接相减。先完成 A～D 的核心数据，再按证据开展阶段 E 的短时定点验证；不要求完整铺开所有 trace 和系统测试组合。

## 1. 实机事实与执行分工

| 项目 | 2026-10-21 只读检查结果 |
| --- | --- |
| SSH | `nvidia@192.168.98.248`，连接成功 |
| 硬件 | NVIDIA Orin NX Developer Kit，约 16 GB 统一内存，aarch64 |
| 软件 | JetPack 5.1.5，L4T R35.6.0，CUDA Runtime 11.4.298 |
| TensorRT | Debian 包 8.5.2；Python API 8.5.2.2 |
| 工具 | `/usr/src/tensorrt/bin/trtexec`；Nsight Systems 2024.5.4；`tegrastats` |
| Python | 系统 Python 3.8.10；已有部署工具使用自身 runtime，不能假定与系统解释器相同 |
| 功耗/时钟 | `nvpmodel -q` 显示 25W、ID=3，但 EMC 查询部分权限不足；普通用户不能执行 `jetson_clocks --show`，**锁频状态未确认** |
| 运行状态 | ROS、状态机、运动控制及其他后台程序正在运行；当前读数不能作为空闲环境 |
| 存储 | `/home/nvidia` 所在分区剩余约 62 GB；属于检查时快照 |

机器人负责 TensorRT Engine 构建、正确性检查、所有性能测量和 trace 采集。本机负责计划、结果整理、表格与图表分析；不使用 RTX 4060 的延迟替代机器人结果。SSH 密码不写入计划、脚本、日志或版本库。

执行前记录背景进程与负载。独立推理测量安排在机器人处于静止且有合适测试窗口时；有并发任务时明确标为该负载下的结果。实际部署负载另做一组。不得自行终止机器人控制进程。当前阶段不调整功耗、时钟、生产配置，也不启动相机或发布测试消息。

## 2. 实验对象与控制变量

机器人现有模型目录：`/home/nvidia/soccer_backend_tensorrt/soccer_perception_ros/models/`。

| 项目 | E01 / E02 统一条件 |
| --- | --- |
| ONNX | `E01_baseline.onnx` / `E02_c3k2.onnx`；优先复用现有图 |
| 输入 | `images`，FP32，NCHW，固定 `[2, 3, 640, 640]` |
| 输出 | `output0`，FP32，固定 `[2, 5, 8400]` |
| ONNX opset | 17 |
| 推理语义 | 原始 one-to-many 输出，外部置信度过滤与 NMS；Engine 层耗时不含外部 NMS |
| 精度 | FP16 tactics，FP32 I/O；逐层实际 dtype 由 Engine Inspector 验证，不称为所有算子均 FP16 |
| batch | 主实验固定 2，对应双目两张图；batch=1 如需研究，另建 Engine、另组比较 |
| 并发 | 主实验单模型、单 inference stream；两模型不并行构建、加载或测速 |
| 功耗 | 主实验沿用并完整记录当前 25W 条件；时钟与背景负载统一并留证 |
| 系统配置 | 两模型使用相同 conf、NMS、top-k、双目、跟踪、可视化、发布频率和场景 |

已读取的源目录 ONNX SHA256：

```text
E01  18b0a86979b053ffaa82e6b3eec0df7a0a36cf6146b6cb719c3269b58ae16074
E02  94b2a3128c990a02fcb88def59ac7b4caa48e130c63a2d013b0e70ab0bd5f3d7
```

两份 ONNX 元数据均记录导出器 `8.3.159`、`half=True`、`dynamic=False`、`simplify=False`、`nms=False`。训练端记录为 Ultralytics 8.4.173。**不要用其他版本对 `nms=False` 的默认解释改变现有图的分支；以实际图、输出和部署代码为准。** 需要重新导出时，独立记录为新 artifact，冻结导出器版本和有效参数，并重新做正确性检查。

现有测速配置实际引用 `install/soccer_perception_ros/share/soccer_perception_ros/models/` 下的 Engine；以上已核验 ONNX 位于源码目录。正式运行前必须解析软链接、核对源码目录与安装目录的文件/hash，以及实际加载的 Python 包和配置，不能假定两处一致。

## 3. 执行顺序

### 阶段 A：冻结测量条件与复核既有基线

1. 独占创建新的远端 run 目录，保存设备、软件版本、工具 `--help`、背景进程、配置快照及模型 hash。
2. 复用机器人 `tool/model_benchmark/`：先用 `--check` 核验实际 Engine 的输入输出和 metadata。该操作会短暂创建 GPU context，留到正式执行阶段。
3. 对现有 E01/E02 Engine 做三轮交错复测，沿用已存在的 100 次预热、每轮 60 秒方案，保存逐次样本。记录运行顺序；临界差异再增加轮次或交换先后顺序。
4. 同步采集约 500–1000 ms 间隔的 `tegrastats`，对齐时间戳，记录温度、GPU/EMC 频率、CPU/GPU 负载、RAM、swap 和可读取的功耗。不把权限不足当作状态已锁定。
5. 如时钟漂移影响结论，可另设固定时钟诊断组：先保存可恢复的原状态，再在合适测试窗口配置，结束后恢复。该组与默认生产状态分开报告，不在本轮计划阶段执行。

阶段 A 的目的是取得有原始记录的当前参照，不能仅引用 E02 报告中“无可测量收益”的历史摘要。

### 阶段 B：在机器人创建可剖析 Engine

保留原有 `.engine` 与 ONNX，在独立 run 下构建新的原始 TensorRT `.plan`，不调用会替换生产 Engine 的 `build_engine.sh --force`。

- 每个模型生成 performance 与 profile 两份 Engine。ONNX、workspace 上限、精度、I/O、tactic sources 等设置相同；performance 使用 `layer_names_only`，profile 在**构建时**设置 `profilingVerbosity=detailed`。
- 正式计时不挂 IProfiler、不运行 nsys。逐层采集使用单独进程，并指定 `separateProfileRun`；详细 NVTX 信息仍可能影响主机开销，因此最终延迟以正常计时为准。
- 先核查历史构建的有效 workspace。当前 YAML 为 `-1`（自动），构建脚本中虽然有 2 GiB 注释，表达式 `value or 2.0` 不会把 `-1` 变成 2.0，不能据注释认定旧 Engine 使用了 2 GiB。
- 新的标准化诊断组建议统一 `workspace:2048` MiB，结合可用内存确认；若与历史条件不同，明确记为新构建组，不声称完整复现旧构建。构建峰值内存可能超过 workspace 上限。
- 顺序构建；记录完整命令、构建日志、Engine hash、大小、耗时、层信息和 timing cache 来源。缓存仅在匹配设备/软件条件下使用；比较组采用相同缓存策略，保留构建前快照。
- profile Engine 与 performance Engine 不是同一个 artifact。比较其层结构、tactics 和正常计时；存在差异时标明，不能将 profile 的每层结果当作 performance Engine 的精确分解。
- 不关闭融合、不标记所有中间 tensor 为输出，不为获得层名而改变正式执行图。

正确性先于正式性能结论：比较同一输入在对应原 Engine、新 performance Engine 和 profile Engine 上的输出，检查 shape、有限值、数值误差、box/score 及一致后处理后的结果。预先固定一组有代表性的 Val 样本（建议 64 张，涵盖 Small/Occluded/Blurred/No Ball，保存名单与 hash）。出现异常时先定位；有检测语义变化或要推广为部署候选时再完成统一全量 Val。E03 不访问 Test，不重训。

### 阶段 C：测量正常推理性能

| 测量 | 计时范围 | 主要指标 |
| --- | --- | --- |
| GPU 常驻输入执行 | CUDA events 包围 TensorRT 执行 | ms/batch 的 mean、P50、P95、P99 |
| 同步执行墙钟 | 主机调用开始到该次 GPU 完成 | execute wall time，反映提交/等待开销 |
| 含传输的 trtexec | H2D、GPU Compute、D2H，分别记录 | 各段时间、enqueue time、qps |
| GPU 常驻 trtexec | 加 `noDataTransfers` | 排除显式 H2D/D2H 后的执行与吞吐 |
| CUDA Graph A/B | 相同 Engine、输入与传输设置，仅改变 Graph 开关 | enqueue 和整体执行变化，判断 launch 开销 |

主对照采用现有 benchmark 的逐次同步口径：100 次预热、三轮、每模型每轮 60 秒。trtexec 作为互补诊断：默认至少 2 秒预热、60 秒测量、1000 次推理，分别保留原始 timings。预热不足、明显温漂或降频时，保留该轮并注明，再在稳定条件下新建轮次。

执行时的范围细化：原有 Engine 与新 performance 版各保留 E01/E02 三轮主对照；详细 profile 版先各做一轮 60 秒正常计时作为诊断校核，异常时再追加。逐层 profile 仍各重复三次，并补采原有 Engine 的直接逐层 profile，以限制重建差异带来的解释偏差。该细化在采集控制器尚未开始 GPU 工作时落实并留痕，不扩展为四种 artifact 的完整重复矩阵。

`trtexec` 会提前提交推理以提高吞吐，其结果不能直接替代应用逐次同步延迟；CUDA Graph、spin-wait 等选项也要单独标记，不能只报告其中最快的组合。使用真实预处理输入回放核查随机输入测量是否具有代表性，输入文件在正式计时前加载。

**batch=2 的耗时是整批延迟；除以 2 只能得到摊销成本。** trtexec qps 是批请求/秒，乘 2 可换成图片/秒；不能把图片吞吐直接称作双目视觉发布 Hz。

### A～C 完成后的判断门槛

先生成一页 checkpoint，列出原有 Engine、新 performance Engine 和新 profile Engine 在**均未挂 profiler/nsys**、相同输入与计时边界下的 mean、P50/P95/P99、逐轮变化、背景负载及正确性结果，再决定后续分析范围。

1. **正确性未通过：**暂停对应 Engine 的正式比较与归因，先处理输出语义或数值异常。
2. **E01/E02 差异未超过重复波动：**例如仍只有约 0.1 ms 时，结合逐轮变化判断可测量性；0.1 ms 是评审提出的参考量级，不是预先认定的测量结果或统一显著性阈值。不启动通道数、expansion ratio 或其他无证据参数搜索，继续阶段 D，集中核查 L19 占比和整网热点。E03 本身不包含缩窄参数搜索。
3. **新旧 Engine 的正常延迟存在稳定且超出同 Engine 重复波动的差异：**暂停“用新 Engine 的逐层结果解释旧 Engine”的结论。先调查实际输入输出、检测分支、精度、workspace、插件、构建器版本、tactic sources、所选 tactics、层融合及 timing cache。需要时另建匹配构建组复测；尚未查清时，阶段 D 只能报告该新 Engine 自身的热点，不能将其解释套到旧 Engine 的约 28 ms。
4. **新旧 Engine 可比且阶段 D 足以解释主要 GPU 耗时：**阶段 E 只围绕主要模块、L19 或提交/等待等尚存疑点做短 trace 验证。若系统目标仍存在未解释的差距，再补充系统路径分析，不机械采集全矩阵。

上述门槛控制结论与后续工作量，不因“E02 无收益”而提前终止瓶颈定位。仍需交付阶段 D 的 Top 20、模块占比和 L19 对照。

### 阶段 D：逐层耗时与模块归因

每模型独立采集三次 profile，建议每次至少 2 秒预热、10 秒采集、200 次推理。导出 `profile.json`、`layers.json` 和日志。TensorRT 汇总通常给出逐层平均时间，不能据此编造每层 P95/P99。

输出两种排名：TensorRT 融合层 Top 20，以及映射回 YOLO 模块的耗时汇总。

| 模块组 | 全局模块编号 / 检查点 |
| --- | --- |
| Backbone | 0–10；关注高分辨率 Conv/C3k2，以及 SPPF=9、C2PSA=10 |
| Neck | 11–22；Upsample、Concat、C3k2=13/16/19/22、下采样与多尺度融合 |
| Detect | 23；分别检查 P3/P4/P5 的回归、分类、解码与输出整理 |
| 执行辅助 | Reformat、Transpose/Shuffle、Copy、Cast 等；标注实际执行和消除情况 |

结构统计保留 Backbone 0–10 与 Neck 11–22。执行时的详细图另确认：除 C2PSA=10 外，L22 的 `/model.22/m.0/m.0.1/` 还包含 PSA/MatMul/Softmax 子块。面向优化决策的互斥主表将 L10 整体及 L22 可识别 PSA 子块列为 Attention，分别从 Backbone、Neck 扣除；块内 FFN 等操作包括在对应块成本中。跨 Attention/Neck 子块边界的融合另列，不强拆时间。另保留结构视角与两个 Attention 块的分项，避免漏计 L22 或重复计时。

利用 ONNX 的 `/model.N/` 节点名、TensorRT layer metadata、tensor 连接、输入输出形状及 NVTX 交叉映射。融合层跨越多个模块时放入“跨模块融合”组；无法映射的放入“未归因”组。不重复计时，也不把融合层强拆成不存在的 PyTorch 子层时间。reshape/concat 等若被优化为无独立执行的操作，明确标记，不分配虚构耗时。

每行至少保存：Engine 层名、类型、源节点/模块、输入输出 shape、dtype/format、tactic、平均 ms/batch、占已采集层时间的比例、跨次波动、映射可信度。层时间总和与正常推理时间单独对照，注明 profiler 开销、融合/异步等限制，不强制两者相等。

重点检查第 19 层：

1. E01 中与该模块相关的融合层合计占多少，以及是否跨模块。
2. E02 内部相关层是否变快，变化是否稳定超过运行波动。
3. 其他模块、Reformat、tactic 或主机开销是否抵消局部收益；E01/E02 的差异不能只按层序号配对。
4. 若第 19 层占比为 p、局部加速为 s，按串行近似用 `1 / ((1-p) + p/s)` 估算整体加速上限；这是解释工具，不是实测收益。GPU 部分收益仍需按其在系统中的占比再折算。

### 阶段 E：按问题定点开展 Nsight Systems 验证与系统分解

阶段 D 后先列出需要验证的假设，再选择对应的 Engine 短 trace 或系统范围。无需对每个 Engine、每个选项都采集 trace。仅分析已构建 Engine 的推理阶段（例如预热后 50–100 次），两模型使用相同采集配置，trace 进程与正常测速分开。

**E0：捕获冒烟测试为强制验收门槛。** `--capture-range=cudaProfilerApi` 依赖目标程序在合适范围实际触发对应的 CUDA Profiler API，不能仅根据 nsys 退出成功或产生 `.nsys-rep` 判定通过。先做一次短采集，保存捕获命令和配置，并在报告或导出的事件中确认：

1. CUDA kernel 记录非空，有有效开始/结束时间，且属于实际 TensorRT 推理；只有 CUDA API 日志、初始化或构建记录不算通过。
2. 捕获窗口内存在多次完整推理，能够与 CPU 提交/API、NVTX 或其他可验证的迭代边界对应；记录是否包含预热及哪些区间被排除。
3. 检查采集警告与丢失事件，确认数据足以支持目标归因。导出事件数、有效窗口、覆盖的完整迭代数及 `trace_smoke_pass` 结果作为证据。

未通过时停止批量 trace 采集及依赖这些数据的结论，先核查目标程序的捕获机制和当前 `nsys profile --help`。必要时改用当前版本支持的短时进程范围捕获，或在独立诊断程序中显式触发 Profiler API/NVTX；重新冒烟验收通过后才扩大采集。失败记录保留，不能以空 trace 表示“GPU 没有工作”。

**E1：强制输出三类时间分析。** 选取同一明确的稳态窗口，同时保留单次推理和连续帧对循环两个视角；事件表记录 Engine hash、线程/stream、窗口、单位和采集覆盖范围。

| 分类 | 必须输出 | 需要解释的问题 |
| --- | --- | --- |
| GPU 实际工作 | kernel 活动区间的并集时长、窗口占比、主要 kernel/模块；memcpy/memset 活动另列 | GPU 在执行哪些工作，主要热点是否与阶段 D 一致 |
| GPU 无工作间隔与等待 | 目标应用无 GPU 活动间隔的总时长、占比、P50/P95/max 和最长间隔的时间线；按证据标注相机/调度等待、CPU 预处理/后处理、提交饥饿或未确定 | GPU 为何不能持续执行，与整网约 28 ms 之外的系统开销有何关系 |
| CPU 提交与同步 | enqueue/launch、拷贝调用、同步/等待 API 和可观测后处理范围的墙钟时长，标明线程和重叠关系 | CPU 时间消耗在提交工作、等待 GPU，还是其他处理与等待 |

GPU 活动按多个 stream 的时间区间取并集，不简单相加重叠 kernel；GPU/CPU 时间也不能作为互斥三段直接求和。CUDA event 包围的执行区间可包含 launch 间隙，不等同于 kernel 忙时长。只有目标应用活动可见时，指标命名为“目标应用无 GPU 工作间隔”；未确认其他进程的活动覆盖前，不能据此声称整块 GPU 空闲。CPU 墙钟范围也不等于 CPU 核心实际忙时长；睡眠、调度等细因没有证据时保留为未确定，若影响决策再定点增加可用的线程调度采集。

根据证据区分：

- GPU 执行时间集中于少数模块：把这些模块列为结构优化候选。
- 大量短 kernel、launch/等待间隙明显，Graph 对照有稳定改善：优先检查提交开销。
- Reformat、Cast 或内存复制明显：检查布局、精度转换和数据驻留。
- Engine 有改善而系统不变：检查相机等待、预处理、NMS、双目匹配、跟踪、ROS、可视化或固定发布频率。
- 温度、频率或并发负载与波动同步：先修正测量条件，再讨论结构收益。

Nsight Systems 的时间线和 GPU 利用率不能单独证明算子是算力瓶颈还是带宽瓶颈。只有这个区分会改变优化决策时，才进一步检查 Nsight Compute 的可用性与计数器权限，对 Top kernels 定点采集；本次只读检查未在 PATH 中发现 `ncu`，不预设可用。计数器采集耗时不作为正常部署延迟。

系统测量复用现有 `tool/model_benchmark/` 的生产循环和统计定义，保存 `detector_ms`、`pipeline_ms`、读取完成/开始到发布的延迟、processing Hz、publish Hz。进一步细分 detector 的预处理、H2D、执行、D2H/候选转 CPU、过滤/NMS，增加必要的 NVTX 范围；主机墙钟与异步 GPU 时间分别解释，不能将重叠阶段直接相加。

先复用已有系统逐帧记录；仅在其不足以解释等待时增补针对性采集。围绕 30/50 Hz 目标，指出稳态帧对周期上的关键路径、可重叠与串行部分，以及发布/相机上限；单独列出未覆盖的等待。不因某层排名第一就认定它是系统第一瓶颈，也不以仅完成 A～D 宣称已解释从约 16.5 Hz 提升的全部约束。

沿用独立测试 ROS 域 87，确认没有生产域冲突且相机可供测试使用；不更换生产模型、不让控制端消费测试消息。统一 conf=0.45、top-k=5 等**运行时有效值**。当前 benchmark 配置有 50 Hz 调度上限、Viser 开启、点云关闭；先测该部署设置，再用独立测试配置取消主动发布等待以观察处理能力，保持相机帧率并记录其上限。触达调度/相机上限时不能据 Hz 相同断言模型没有收益。系统场景不可完全重现，固定场景并交错重复，明确其局限。

## 4. TensorRT 8.5.2 命令骨架

以下是机器人端命令骨架；实际执行参数、退出状态与耗时以 run 中 `commands.jsonl` 和各阶段日志为准。已按实机 `--help` 核对：8.5.2 使用 `--buildOnly`、`--streams=1`；不直接照搬新版的 `--skipInference`、`--infStreams` 等选项。

在独占 run 目录下，先确认两份固定 shape ONNX 与上述 hash 一致，再以 E01 为例：

```bash
TRT=/usr/src/tensorrt/bin/trtexec
MODEL_DIR=/home/nvidia/soccer_backend_tensorrt/soccer_perception_ros/models

# 新的 2 GiB workspace 标准化诊断组；每个输出文件必须尚不存在。
"$TRT" --onnx="$MODEL_DIR/E01_baseline.onnx" \
  --saveEngine=E01_perf.plan --fp16 \
  --inputIOFormats=fp32:chw --outputIOFormats=fp32:chw \
  --memPoolSize=workspace:2048 \
  --profilingVerbosity=layer_names_only --buildOnly \
  > E01_build_perf.log 2>&1

"$TRT" --onnx="$MODEL_DIR/E01_baseline.onnx" \
  --saveEngine=E01_profile.plan --fp16 \
  --inputIOFormats=fp32:chw --outputIOFormats=fp32:chw \
  --memPoolSize=workspace:2048 \
  --profilingVerbosity=detailed --buildOnly \
  > E01_build_profile.log 2>&1

# 正常计时；不附加 layer profiler。
"$TRT" --loadEngine=E01_perf.plan --streams=1 \
  --warmUp=2000 --duration=60 --iterations=1000 \
  --noDataTransfers --percentile=50,95,99 \
  --exportTimes=E01_times_gpu.json > E01_timing_gpu.log 2>&1

# 独立归因采集；其 profile 时间不作为正式部署延迟。
"$TRT" --loadEngine=E01_profile.plan --streams=1 \
  --warmUp=2000 --duration=10 --iterations=200 \
  --noDataTransfers --separateProfileRun \
  --dumpProfile --exportProfile=E01_profile.json \
  --dumpLayerInfo --exportLayerInfo=E01_layers.json \
  > E01_profiling.log 2>&1

# E0 冒烟命令候选，仅 load 已构建 Engine；验收通过前禁止扩展为批量采集。
# cudaProfilerApi 范围须确认目标程序确实触发；生成报告文件本身不代表通过。
nsys profile --trace=cuda,nvtx,osrt --sample=none --cpuctxsw=none \
  --capture-range=cudaProfilerApi --capture-range-end=stop -o E01_trace \
  "$TRT" --loadEngine=E01_profile.plan --streams=1 \
  --warmUp=2000 --duration=0 --iterations=100 --noDataTransfers \
  > E01_nsys.log 2>&1
```

固定图已包含 batch=2，不需要动态 shape profile。E02 用同一骨架和独立文件名；各重复轮次放入各自子目录。Graph A/B 仅新增 `--useCudaGraph`，Graph trace 需要时加 `--cuda-graph-trace=node`；含传输对照去掉 `--noDataTransfers`。Nsight 命令必须先通过阶段 E0 的非空 kernel、完整推理范围与覆盖有效性验收，再用于定点采集；空 trace 不进入统计。示例关闭 CPU sampling/context-switch 采集，不能据此生成 CPU 调度或线程实际运行时间结论。

实机 Nsight 2024.5 的 `capture-range-end` 默认为 `stop-shutdown`，会在结束采集范围时终止目标进程。首次冒烟因此返回 143，已保留记录；实际采集改用 `stop`，让程序写完验证输出并正常退出，再验收事件范围。

新 `.plan` 是原始 TensorRT 序列化文件，可用于 trtexec 和现有工具的 engine 模式。Ultralytics `.engine` 可能含自定义 metadata 头；不能假定可被 trtexec 直接读取，也不能只改后缀冒充兼容。系统模式需要对应的 Ultralytics 元数据，优先保留现有 Engine；若要测新 Engine 的完整系统性能，在 run 内按实际加载器协议建立经验证的封装副本，保留原始 `.plan` 和精确对应的 metadata。

实机控制器在 engine-only 模式也强制检查 `.engine` 后缀。实际用字节一致的 `.engine` 硬链接别名适配此入口，并保存哈希证明；其内容仍为原始 TensorRT Engine，不含 Ultralytics 头，不交给系统加载器。初次入口失败记录保留。

## 5. 归档与完成条件

建议远端目录：`/home/nvidia/soccer_backend_tensorrt/results/E03_tensorrt_profiling/<UTC_run_id>/`；本机回收至 `experiments/E03_tensorrt_profiling/runs/<UTC_run_id>/`。run ID 独占新建，已有文件不覆盖。仓库现有规则忽略 `experiments/E*/runs/`。

保留环境/配置/指纹、构建日志与 Engine、正确性检查、A～C checkpoint、正常计时原始样本、逐层 JSON、模块映射 CSV、Top 20 CSV、逐轮统计、tegrastats，以及按需采集的 trace、E0 冒烟验收与三类时间分析。run record 初始状态为 planned/not_run，未测结果为空；中断或失败留痕。可审阅的最终 `REPORT.md` 放在实验目录外层，重型产物留在 runs，不自动提交上传。

**首要交付是模块耗时与优化优先级表，而非原始文件集合。** `REPORT.md` 首页使用以下模板，并附可定位到原始证据的链接：

| 模块/环节 | 当前耗时（注明 ms/batch 或 ms/帧对） | Engine 占比 | 优化证据与局限 | 是否值得进入 E04 / 优先级 |
| --- | --- | --- | --- | --- |
| Backbone（不含 Attention） | 待测 | 待测 | TensorRT Profile，注明对应 Engine | 待定 |
| Neck（不含 L22 内 PSA 子块） | 待测 | 待测 | Profile、Reformat 与层映射 | 待定 |
| Attention（L10 C2PSA 与 L22 内 PSA） | 待测 | 待测 | MatMul/Softmax 等实际执行层、按需 kernel trace | 待定 |
| Detect Head | 待测 | 待测 | TensorRT Profile 与输出处理边界 | 待定 |
| 执行辅助、跨模块融合及未归因 | 待测 | 待测 | 层元数据与归因覆盖率 | 待定 |
| 数据传输与同步 | 待测 | 不适用 | 正常计时、按需 Nsight；标注同步与 GPU 的重叠 | 待定 |
| 其他 CPU 处理及调度/相机等待 | 待测 | 不适用 | 系统计时、三类时间分析；未覆盖部分说明原因 | 待定 |

表中 Engine 占比统一以同一 Engine 的已采集层时间之和为分母，并注明它不是无 profiler 正常整网延迟的精确占比。L10 Attention 从 Backbone 扣除，L22 内 PSA 从 Neck 扣除，跨模块/子模块融合单列；外部传输/同步及 CPU 环节不混入 Engine 百分比。表格为 E01、E02 分别给值或明确注明主表为 E01，并另列 E02 差值。耗时、证据和优化建议必须使用同一 Engine 身份；未采集项写 not_run/未测及原因。

**阶段 A～D 核心交付必须完整：**

1. E01/E02 相同条件下的正常推理延迟分布和逐轮变化，区分原 Engine 与新标准化构建。
2. 两模型各自的 TensorRT 执行层 Top 20，逐行标注 YOLO 模块、输入输出 Tensor Shape、dtype/format、tactic、平均耗时和占比；无法映射或读取的字段明确注明。
3. Backbone/Neck/Attention/Detect/辅助操作占比，以及映射覆盖率、跨模块融合和未归因部分。
4. 第 19 层局部变化、整体变化与波动范围，基于 tactic/层结构解释无收益的可能原因；需 trace 验证的保留为假设。
5. 首页模块优先级表与排序后的 2–3 个后续实验候选，各有证据、预期作用范围、潜在精度代价和验证方式。局部变快但整体未超出重复波动时，结论仍写“未测得稳定整体收益”。

**阶段 E 按问题补足证据：** trace 一旦用于结论，必须提供 E0 验收和 GPU 工作/无工作间隔/CPU 提交同步三类分析；系统分析明确从约 16.5 Hz 接近 30/50 Hz 的待解决约束。未开展的组合写 not_run 及原因，可说明阶段 D 已解释的范围和仍未解决的问题；不能把阶段 E 未测项填成零或声称完整系统瓶颈已全部定位。

优先级为：**A～C 基线/正确性/正常计时 → checkpoint 判断 → D 的 Top 20、模块占比与 L19 对照 → E0 冒烟验收 → 按未解决问题做 Nsight/系统定点验证 → E04 建议**。A～D 优先完成，阶段 E 以补足证据为边界；不自动扩展为通道搜索、全矩阵 trace 或网络修改。运行时长取决于构建、热稳定和测试窗口，不在实测前承诺完成时间。

## 6. 依据

- [E01/E02 阶段报告](../../benchmarks/E01_E02_REPORT.md)与[E02 原计划](../E02_c3k2/PLAN.md)。
- 机器人实际 `trtexec --help`、ONNX 图与 metadata，以及 `tool/model_benchmark/README.md`、配置和构建入口；实机行为优先于其他版本示例。
- [NVIDIA TensorRT 8.5.3 Developer Guide](https://docs.nvidia.com/deeplearning/tensorrt/archives/tensorrt-853/pdf/TensorRT-Developer-Guide.pdf)：与实机相近版本的 profiler、NVTX 与 Nsight 方法。
- [NVIDIA TensorRT 性能测量方法](https://docs.nvidia.com/deeplearning/tensorrt/10.x.x/performance/measurement-techniques.html)：计时边界与 profiler 的解释；API 细节须按 8.5.2 适配。
- [Jetson tegrastats](https://docs.nvidia.com/jetson/archives/r35.6.2/DeveloperGuide/AT/JetsonLinuxDevelopmentTools/TegrastatsUtility.html)：设备遥测指标。
