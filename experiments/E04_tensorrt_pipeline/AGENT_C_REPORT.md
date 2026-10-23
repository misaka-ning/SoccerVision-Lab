# E04 Agent C：预处理与数据流

当前状态（2026-10-22）：单项及组合正确性、100个有效性能作业已审查，后续实验按用户要求暂停；未生产采用、未通过B5长稳。以下保留历次开发语境，最新结论见末尾。

## 实际发现与修改

已读取实际安装版 `ultralytics_0/engine/predictor.py` 与 `data/augment.py`。原路径为：原 `pre_transform` → `np.stack` → BGR/RGB 视图 → BCHW 视图 → `ascontiguousarray` → `torch.from_numpy` → 阻塞 `to(device)` → FP32 转换 → 除以 255。现有 letterbox 使用 OpenCV `INTER_LINEAR` 和 114 padding；本候选直接调用原 `pre_transform`，没有重写 resize、padding 或坐标映射。

只新增以下专有文件：

- `soccer_perception_ros/soccer_perception/optimizations/preprocess.py`
- `soccer_perception_ros/tests/test_e04_preprocess.py`
- 本报告 `E04_AGENT_C_REPORT.md`

没有修改公共配置、适配器、包初始化、部署依赖、模型、Engine、NMS、检测阈值、ROS 或生产文件。

| 开关 | 行为 | 是否进入性能候选 |
|---|---|---|
| `c0`，默认 | 原方法完全不挂接、不分配缓冲 | 基线 |
| `c1` | 保持原操作顺序，记录八段方法墙钟聚合值 | 仅诊断探针；不作为加速版本 |
| `c2` | 保留原 letterbox，按左/右目直接 RGB/CHW copy 到复用的 uint8 BCHW host buffer | 待机器人独立正确性和 A/B |

`c1` 的八段为 `pre_transform`、`stack`、`color_layout_views`、`contiguous_pack`、`from_numpy`、`to_device`、`dtype`、`normalize`。记录 count、total/last/max/mean 毫秒，不保留随帧数增长的数组，不新增 CUDA synchronize。`pre_transform` 包括原 resize 和 padding；没有为了拆开它而全局替换 OpenCV 函数。dtype/normalize 的方法墙钟含异步提交或等待，不能解释为 GPU kernel 耗时，也不能直接与 Engine event 时间相加。探针自身存在 Python 计时开销。

`c2` 每个稳定输入流只分配一次 2,457,600 字节 host buffer 和一个共享该 buffer 的 Torch CPU 视图。逐目 `np.copyto` 从 letterbox 输出的 CHW/RGB 视图直接写入最终 BCHW buffer，省去原 `np.stack` 临时 batch；稳态也无需重新分配最终 contiguous host batch。这里减少的是 host 分配和复制；GPU 传输、FP32 转换、归一化没有改变。节省内存访问次数不能直接换算为延迟收益。

## 生命周期与失败处理

- 输出仍是连续 FP32 `[2,3,640,640]`，实际部署 device 沿用 predictor.device。
- host buffer 由 handle 持有；不引用或改写调用方图像，不保留时间戳、帧对象或队列。
- 保留原默认阻塞 `Tensor.to(device)`，不启用 pinned/non_blocking。返回前 host→device 读取已完成，下一次 pack 可以安全复用 host storage。
- 不复用 GPU 输入或输出。uint8 转 float 会生成独立 FP32 Tensor；调用者可以保留上一批输出，后续 pack 不会覆盖它。Graph 可以把当前 Tensor 复制到 B 自有的稳定缓冲区；C 不改变 stream。
- handle 内有锁，串行化本实例的 host pack、传输与 restore；实际 predictor 自带推理锁也继续保留。
- 仅接收两个同形状 uint8 HWC3 图像。首次成功后冻结原图 shape；batch、dtype、左右 shape、后续 shape、640 输入尺寸、FP16 或动态后端不符时，调用保存的原方法，增加 `fallback_count`，记录原因和当次 `effective=c0`。
- 打包或转换异常有可见 fallback；原方法也失败时异常继续上抛。回退不是正确性通过，正式轮次必须检查计数。
- `restore()` 幂等、无条件恢复保存的原方法，移除实例 hook/marker 并释放 host buffer。`describe()` 提供 requested/effective、calls/success/fallback、最后错误、shape、device、buffer ownership/分配次数和探针统计。

## 已运行验证

使用本机 `/home/misaka/miniconda3/envs/soccer_perception/bin/python`，Torch `2.4.1+cu121`、NumPy `1.24.4`、OpenCV `5.0.0`，`torch.cuda.is_available() == False`。这些版本与机器人不同，以下结果只能证明 CPU 语义与内存所有权，不能证明 CUDA 性能或完整检测/定位正确性。

命令（从本 worktree 的 `soccer_perception_ros` 运行）：

```bash
E04_C_REFERENCE_RUN=/home/misaka/workspace/experiments/E04_tensorrt_pipeline/runs/20261022T020842Z_78f1b7 PYTHONDONTWRITEBYTECODE=1 /home/misaka/miniconda3/envs/soccer_perception/bin/python -m unittest tests.test_e04_preprocess -v
```

结果：**12 项通过，1.757 秒**。覆盖原路径不挂接、BGR/RGB、padding、左右顺序、输入不变、连续 FP32 shape、12 次变化画面、旧输出 ownership、一次分配、shape 改变/不对称、非连续数组、batch/dtype/Tensor 输入回退、backend 配置回退、打包异常、计时结果、无新增 synchronize、恢复/重复安装和错误初始化。

第 12 项读取已冻结 manifest 中的 **61 对、122 张 Val**，每个原始图像打开前检查目录属于 `images/val` 且 SHA256 与冻结 manifest 相符；未访问 Test。测试执行已审计的 LetterBox 类源码，调用本机 OpenCV，得到：

| 检查 | 结果 |
|---|---|
| c2 对同机原路径 CPU FP32 input | 61 对逐元素完全相等 |
| c2 CPU input 对机器人冻结 Golden input | 最大绝对差 `5.960464477539063e-08`，不超过 1 个 FP32 ULP |
| 61 对有效 c2 调用 / fallback | 61 / 0 |
| 连续变化输入时 host buffer / view 分配 | 各 1 次 |
| 旧 FP32 输出被后续复用覆盖 | 未发生 |

该 1 ULP 差异也存在于原 CPU 计算与冻结 CUDA 输入的比较，不能当作候选造成的检测退化。机器人仍需检查候选 CUDA input 与同机原路径逐元素相等；不能据此 CPU 结果宣称候选 raw、检测框、匹配、三维定位或 ROS 全部通过。

初次可选 Val 测试使用了未展开的 `val_cases/images` 路径而失败；已改为只读 manifest 记录的 Val 原始路径并逐图校验哈希，最终完整测试通过。失败没有触发任何模型/源码/数据覆盖。

## 实测性能与后续验收

协调 Agent 冻结的原始固定图基线 preprocess 方法墙钟均值 **9.523 ms**、完整检测器 **59.373 ms**。本 Agent 没有运行优化候选的实机测试，**c2 的预处理、传输、检测器墙钟、系统 Hz、P95/P99 和内存稳定性均待测**，不声称收益。

根协调 Agent 集成示例（已初始化 predictor，正式预热前）：

```python
from soccer_perception.optimizations.preprocess import install
handle = install(detector, "c2")  # independent C-only candidate
try:
    # Golden validation, then coordinated robot warmup/measurement
    info = handle.describe()
finally:
    handle.restore()
```

验收顺序：

1. 用 `c1` 短时诊断八段方法墙钟，保存 describe；不把探针数据作为 c2 收益。
2. 单独 `c2` 在机器人对 61 对 Val 比较 CUDA input、raw、最终框/顺序/左右归属、候选/双目匹配、三维定位和七字段 ROS；确认没有 fallback，变化画面没有旧帧。
3. 单独 R3（其他开关关闭）与 R0 交错，100 预热、每组 60 秒、至少三轮，同时收集 preprocess、transfer、完整检测器和完整系统数据及 P95/P99。长脚本由用户运行；本 Agent 不进行 SSH 或 GPU 工作。
4. 验证 shape 不支持时能够恢复基线，检查 GPU memory 和连续调用稳定性；只有单项正确性和重复收益成立，再组合 Graph 与 A。

没有实现 C3 GPU resize、C4 异步重叠或 C5 双缓冲。当前没有 c2 实机收益或 resize 热点分段证据；GPU resize 还需量化 OpenCV 几何/插值数值差异并传递到检测/定位验收。提前引入新 GPU resize、跨流缓冲和队列会扩大尚未验证的改变范围。后续是否实施由协调 Agent 根据独立结果决定。

结论：达到 **C 开发/CPU 验证交付门槛**；尚未达到 **实机正确性、性能与生产集成门槛**。

## 协调补充：实机正确性回收

phase1单项实机正确性已通过：7变体各61对NPZ字节一致，语义零差异、零fallback、恢复完整；Graph 71case和161次检测器重放验证通过。A2 138次D2H/6840字节；C2单host/view各分配一次。此补充不代表正式性能或长期稳定性通过，详见CORRECTNESS_REPORT.md。

## 协调补充：28轮离线正式性能验收

C2预处理三轮节省0.353/0.290/0.300ms，但检测器节省0.832/-0.004/0.052ms，后两轮小于R0漂移。host/view始终各1次、2457600字节、正式新增分配0，零fallback/restore完整。C1准确扣除100warm后1023次，pre_transform6.260ms占八段方法墙钟约66.1%，to_device1.330、contiguous_pack1.143ms；八段和9.475 vs preprocess方法9.661ms，探针/未分段开销约0.186ms。GPU异步方法墙钟不是互斥kernel/memcpy时间。

独立Agent审查记录位于对应worktree的E04_*_OFFLINE*文件；统一统计、局限与下一步以PERFORMANCE_COMPARISON.md、REPORT.md和NEXT_RUN.md为准。

## 无球system补充

无球system C2 processing宏+0.579%，仅空检测场景；有球system待测，组合仍不批准。用户要求手动检查有球，未采用任何scene_validation草稿。

## 有球单项审查与组合正确性阶段

有球C2三轮平均收益重复、约0.48～0.70ms read-ready改善；第2轮P99回退0.922ms。正式采样全408MHz，host/view仅1次、zero fallback/restore通过。仅准入R4-vs-R5增量诊断和Golden，不默认采用；C2/Graph输入存储和流等待复核无冲突。

## 组合正确性已审查与正式性能准入

R5的61对输入/raw/候选及下游语义精确一致；C2成功161、host/view各1次，零回退、恢复完整。新矩阵比较同轮R5对R4的C2增量，须连同P95/P99评估；仍仅诊断。用户拒绝的scene_validation草稿未采用。

正式组合收益仍not_run，见PERFORMANCE_COMPARISON.md；回收与六份独立审查见RAW_DATA_INDEX.md。


## phase5最终组合审查与暂停

C2局部预处理三轮省0.322/0.382/0.362ms；R5对R4系统Hz+1.610/−0.218/+0.911%，增量不稳定，继续可选不默认。C2每调用成功、host/view各1次；帧关联通过。遥测已按UTC/重启会话筛选，未实施GPU Resize/异步/双缓冲；现场有效率不等于物理精度。

本轮完整回收293文件，35attempt中30complete入统计、4superseded和1failed排除；独立复核见phase5/independent_reviews/E04_C_FINAL_REVIEW.md/json，所有报告以REPORT.md及PERFORMANCE_COMPARISON.md最新同phase表为准。后续暂停，不再启动测试。
