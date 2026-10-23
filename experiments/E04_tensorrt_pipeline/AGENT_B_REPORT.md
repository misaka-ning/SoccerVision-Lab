# E04 Agent B：固定 Engine 的 CUDA Graph 候选

当前状态（2026-10-22）：单项及组合正确性、100个有效性能作业已审查，后续实验按用户要求暂停；未生产采用、未通过B5长稳。以下保留历次开发语境，最新结论见末尾。

## 实际调查

- 工作树来自部署源码私有快照 `b7dab3a1a738c73d3a64614f5aab7b4b1ef328f0`，上游为 `5ef358e9b7df2edcf36d4618d3e2b6aad70e0812` 加已冻结的原有修改；以 E04 主 run 的 source manifest 为实际内容依据。
- E04-0 的 `E04_0_GATE.json` 已由协调 Agent 审查通过。没有把旧 `E04_SOURCE.json` 中的准备阶段状态当作新验收结果。
- 已读取实际安装版 `audit/source/installed/ultralytics_0/nn/autobackend.py`。TRT 分支为 `binding_addrs['images']=im.data_ptr()`、`context.execute_v2(...)`、返回 binding output；未实现 Graph capture/replay。
- 原 Engine 为静态 explicit batch，外部 FP32 `[2,3,640,640] -> [2,5,8400]`。FP16 tactics 不表示可以改变外部 I/O dtype。
- E04-0 的 Engine 均值 28.136 ms；E03 Graph 的 28.537→26.406 ms 是独立诊断，不能当作本候选或生产系统收益。

## 修改与接口

仅新增：

- `soccer_perception_ros/soccer_perception/optimizations/graph.py`
- `soccer_perception_ros/tests/test_e04_graph.py`
- 本报告

`install(detector, 'b0'|'graph') -> handle` 在 predictor/backend 初始化后安装；默认 `b0` 完全保留原方法，不分配 GPU 资源。`graph` 只替换这个 backend 实例的 `forward`，不修改 site-packages、模型、原 Engine、配置、NMS、预处理或 ROS。

handle 提供 `describe()`、`synchronize()` 和 `restore()`。状态区分 `pending_capture`、`graph`、失败禁用后的 `b0`、`restored`，同时记录 fallback/last_error/disabled_reason/cleanup_error、capture/replay/input_update/warmup_enqueue/output_clone 次数、I/O shape/dtype/output names/device 及自身分配状态。计数表示成功提交的操作，CUDA 完成仍需同步或读取输出确认；`describe()` 本身不插入同步。

## 捕获、数据更新和生命周期

1. 第一次合规输入到达时，用**相同只读 Engine 对象创建独立 execution context**，分配独立固定 input/output 和非默认 Torch CUDA stream。原 backend 的 context、binding 对象与 binding_addrs 不修改。
2. 检查 TRT 8.x、非动态、explicit batch、两 binding、固定形状、FP32 CUDA 连续输入。先拷贝本次输入并在专用 stream 上执行三次 enqueue，再在捕获外完成同步。
3. 捕获中仅调用 `execute_async_v2`；检查其布尔返回，捕获中没有分配、复制、NMS 或 host synchronize。
4. **每一次**有效 forward 均执行：caller stream → 专用 stream 等待 → 本次 input copy → replay → 图外 output clone → caller 等待。记录源输入跨 stream 的 allocator 生命周期。首次返回也经过 replay，预热或捕获阶段结果不会冒充本次检测输出。
5. 图外 clone 为每个返回值提供独立 storage，允许既有 NMS 原地改写，同时防止下一次 replay 改写上一次结果。这增加约 336 KB/次的 GPU output copy，必须纳入实测，不能假设免费。
6. 独占锁串行提交；不存在隐藏队列、双缓冲或独立帧采集。当前输入左右顺序和时间戳由既有检测器保持。
7. restore 等待本 stream 完成，再释放自己的 Graph、context、I/O、地址和 stream 引用，恢复原实例方法/类方法状态，不调用全局 `empty_cache()`。恢复时发现另一个所有者改了 forward 会报错，不覆盖该所有者。

## 失败与回滚

捕获、enqueue 或 replay 的同步 Python 错误会记录失败并永久禁用本 handle，先收束私有 stream，再以**当前输入及原参数**调用原 forward。不得把 effective=b0 的时间计入 Graph 结果。

异步 CUDA 错误可由 `handle.synchronize()` 或输出读取显式发现。若清理同步也失败，抛出 `GraphExecutionError`，拒绝返回旧输出；不能承诺已经失效的 CUDA context 仍可安全恢复。restore 先恢复原方法，安全清理失败会保留私有资源所有权并报错，可再次 restore 重试。

回滚：调用 `handle.restore()`，或候选独立进程退出。下次独立进程使用 `b0`。未改生产源码或配置，不需要覆盖原 Engine 回滚。

## 已运行的正确性测试

本机 Python 环境的 Torch 为 `2.4.1+cu121`，CUDA 不可用；机器人为 Torch `2.0.0+nv23.05`。本次仅执行 CPU 状态与 mock stream/Graph 测试，**不能证明机器人 CUDA capture 或 TRT 正确性**。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=soccer_perception_ros \
  /home/misaka/miniconda3/envs/soccer_perception/bin/python \
  -m unittest discover -s soccer_perception_ros/tests -p test_e04_graph.py -v
```

13 项通过，覆盖：b0 零挂接/零分配；变化输入结果更新及独立输出；原 context/地址不变；capture 仅一次；流等待方向；释放资源与恢复原方法；原有实例 forward；不支持 backend/输入的回退；capture exception；TRT enqueue false；replay exception；异步错误拒绝旧结果；清理可重试；重复安装拒绝；不覆盖其他 patch 所有者。`git diff --check` 和 Python 3.8 AST 语法检查通过。

## 交给协调 Agent 的实机验证入口

所有 GPU/相机/ROS 工作由协调 Agent 统一排程，耗时脚本由用户启动。本 Agent 没有 SSH、启动 GPU benchmark 或停止机器人进程。

初始化检测器后：

```python
from soccer_perception.optimizations.graph import install
handle = install(detector, 'graph')
# 既有 detector/predictor 继续使用原调用方式。
handle.synchronize()  # 正确性/健康检查边界；不应默默加入每个正式计时样本。
status = handle.describe()
handle.restore()
```

| 阶段 | 需要执行和保存的证据 | 当前状态 |
|---|---|---|
| B1 Engine 固定输入 | 原 forward 的 raw output 立即 clone 后与 Graph 对照；相同输入/Engine 的交错 event A/B | 未运行 |
| B2 多组真实输入 | 61 组 Golden FP32 input 按顺序/交错重复，逐组比较本次 baseline/raw Golden 与 Graph；检查输入确实变化、输出不复用旧 storage、首次输出与左右归属 | 未运行 |
| B3 检测器 | 原阈值和 NMS 的候选/框/坐标/置信度/顺序/定位协议 Golden 对照；三轮 100 warmup、60 秒交错 wall A/B | 未运行 |
| B4 完整系统 | 安全测试窗口、ROS87、相同场景/Viser/负载，周期/Hz/publish/P95/P99 与输出正确性 | 未运行 |
| B5 稳定性 | 连续变化输入、capture_count 恒为1、replay_count=input_update_count、fallback=0；记录 Torch memory allocated/reserved、设备可用内存和进程 RSS，restore 后复查 | 未运行 |

TRT context 内存并不全部体现在 Torch allocator，B5 不能只看 `memory_allocated()`。Graph 成功的最低条件为 `effective='graph'`、`capture_count=1`、`replay_count=input_update_count>0`、`fallback_count=0`，且输出读取/同步无 CUDA 错误；通过此条件仍需要最终语义和性能验收。

建议 raw output 的误差阈值由协调 Agent 先记录零容差结果和 max_abs/max_rel，再依据基线同输入重复性决定是否接受浮点差异；禁止以放宽最终检测/定位容差掩盖旧输入错误。不可跳过密集/边界/排序语义对照，因为原 NMS 会改写预测坐标。

## 收益、风险与验收结论

性能收益：**未测，不报告加速值**。候选增加了输入 device-to-device copy、output clone 和独立 TRT context 的常驻内存，Graph 节省的提交成本必须足以抵消它们。动态时钟、输入 copy、NMS 同步和系统等待可能使 Engine 诊断收益无法转化为系统收益。

主要未决项为机器人 Torch2.0/TRT8.5 的真实 capture 兼容性、plugin/capture 支持、独立 context 内存及长时行为、异步错误可检测性和 B2 变化输入验证。CPU/mock 通过仅允许进入短时实机正确性冒烟，不批准生产或正式性能结论。

流同步/allocator 设计参考 [PyTorch CUDA semantics](https://docs.pytorch.org/docs/stable/notes/cuda)；TRT enqueue/capture 的预热要求参考 [NVIDIA IExecutionContext API](https://docs.nvidia.com/deeplearning/tensorrt/archives/tensorrt-861/api/c_api/classnvinfer1_1_1_i_execution_context.html)。这些文档用于设计约束，不能代替本机 Torch2.0/TRT8.5 的实测验收。

## 协调补充：实机正确性回收

phase1单项实机正确性已通过：7变体各61对NPZ字节一致，语义零差异、零fallback、恢复完整；Graph 71case和161次检测器重放验证通过。A2 138次D2H/6840字节；C2单host/view各分配一次。此补充不代表正式性能或长期稳定性通过，详见CORRECTNESS_REPORT.md。

## 协调补充：28轮离线正式性能验收

完整forward CUDA event三对29.670→27.934、29.554→27.979、29.518→28.007ms；完成墙钟同步下降。固定图检测器配对下降1.588%/1.337%/2.375%。全部capture1、update/replay=100+样本、零fallback、restore释放资源标志；60秒采样allocated/reserved平稳不等于长稳。第二轮Graph P95 59.646ms比首端R0 59.385ms稍高，虽低于首尾合并R0，不声称优于每个基线端点。0.9ms inference方法墙钟仅异步提交，不能当GPU完成。

独立Agent审查记录位于对应worktree的E04_*_OFFLINE*文件；统一统计、局限与下一步以PERFORMANCE_COMPARISON.md、REPORT.md和NEXT_RUN.md为准。

## 无球system补充

无球system Graph processing三轮配对宏+0.962%，但第一轮P95略差；capture/update/replay/restore通过。仅准入有球单项，不批准组合/长稳/生产。

## 有球单项审查与组合正确性阶段

有球Graph processing宏+2.536%，每轮capture1/update=replay=N+100/zero fallback/restore通过。相对合并首尾P95/P99改善，但第二轮cycle P99比首端+0.230ms。源码交叉挂接/clone/等待/恢复未见冲突，仅准入R4 Golden，未准入生产/长稳。

## 组合正确性已审查与正式性能准入

R4/R5各61对input/raw/最终语义一致；capture1、Replay/update/clone161、零回退和完整恢复。B5工具在Agent B私有提交597cd2c4606c738ca6b03f3b0511d0e944c2ae77准备，7项CPU/mock通过，尚未运行GPU长稳；不纳入此次30组采集，不据60秒任务声称无泄漏。

正式组合收益仍not_run，见PERFORMANCE_COMPARISON.md；回收与六份独立审查见RAW_DATA_INDEX.md。


## phase5最终组合审查与暂停

R4对同期R0 system宏+6.928%，对A2再+3.246%，三轮一致；12个Graph作业capture1、replay/update/clone闭合、零回退、restore完整。R4读取完成至发布P95/P99相对同期A2与R0端点均改善，仍有稀有尖峰。B5未运行，不批准长期无泄漏或生产采用。

本轮完整回收293文件，35attempt中30complete入统计、4superseded和1failed排除；独立复核见phase5/independent_reviews/E04_B_FINAL_REVIEW.md/json，所有报告以REPORT.md及PERFORMANCE_COMPARISON.md最新同phase表为准。后续暂停，不再启动测试。
