# E04 Agent A：后处理与最终结果回传

当前状态（2026-10-22）：单项及组合正确性、100个有效性能作业已审查，后续实验按用户要求暂停；未生产采用、未通过B5长稳。以下保留历次开发语境，最新结论见末尾。

## 依据与实现边界

已核对 `E04_0_GATE.json` 为 passed（2026-10-22），私有基线提交 `b7dab3a1a738c73d3a64614f5aab7b4b1ef328f0`，部署上游 HEAD `5ef358e9b7df2edcf36d4618d3e2b6aad70e0812` 带既有修改。工作树为 `runs/20261022T020842Z_78f1b7/worktrees/agent_a`。E04_SOURCE/INTERFACES 的旧阶段文字不代表新门禁状态，以协调 Agent 的实际 gate 为准。

修改仅新增：

- `soccer_perception_ros/soccer_perception/optimizations/postprocess.py`
- `soccer_perception_ros/tests/test_e04_postprocess.py`
- 本报告。

未访问冻结 Test；只读取 E04-0 已冻结的 61 对 Val Golden。没有 SSH、机器人 GPU/相机/ROS 运行、依赖安装或全局算子替换。

## 实际调用与瓶颈证据

生产 `YoloBallDetector.detect_candidates_batch` 调用 `model.predict(list(frames), ...)`。实际固定配置是 conf=0.45、class=[0]、IoU=0.7、max_det=300、top_k=5。Ultralytics 原后处理先按 `score > conf` 过滤、原 NMS、恢复坐标，随后 detector 转换每目 `xyxy/conf/cls`：每个非空目各三次 `detach().cpu().numpy()`；class 另有 `astype(int)`。所有候选构造完毕后 Python 稳定降序排序，最后才做正数 top_k 切片。负数、零、None 均不截取。

没有在 NMS 前将全部 8400 个框传回 CPU 的代码。实际六个转换入口传的是 NMS 后的少量框。原 fallback 的 `scores.argsort(descending=True)` 和 `rest[iou <= threshold]` 会产生 GPU kernel 及动态索引/同步；本次保留这一条 NMS 路径，包括并列分数行为。

E04-0 的 torchvision 0.15.0 `_C.so` 加载错误为 `undefined symbol: _ZNK5torch8autograd4Node4nameEv`，Torch 为 `2.0.0+nv23.05`，实际 NMS 为 `soccer_perception.adapters.yolo.nms_fallback`。该错误属于编译扩展与 Torch ABI 不兼容，不能通过调用原 torchvision CUDA ops 绕过。未全局更换 Torch/Torchvision/CUDA。

固定图基线由协调 Agent 提供：后处理墙钟 13.711 ms，候选结果转换墙钟 4.151 ms，检测器墙钟 59.373 ms，独立 Engine 28.136 ms。这些范围不是彼此可直接相加的独立 GPU 成本。A2 会把结果打包成本移至 `model.predict` 返回之后、原 candidate 转换之前，因此只看原 converter 计时降低不能证明整网加速。

## 分离开关

导入模块不启用优化。`install(detector, variant='a0')` 返回 `describe()/restore()`；variant 大小写规范化为小写，未知值立即失败，同一实例不允许重复安装。

| 变体 | 实际改动 | 保留内容 |
|---|---|---|
| a0 | 无挂接 | 完整原路径 |
| a1 | 仅将已回 CPU 的数组一次 `tolist()`，减少循环中的标量拆箱与重复查找 | 原三次/目转换、原 NMS、所有候选构造、稳定排序和末尾 top_k |
| a2 | 包装该 detector.model 实例的 predict，原 predict 完成后，将两目最终六列 Boxes.data 在 GPU cat 一次、blocking `.cpu()` 一次，浅拷贝 Results/Boxes 指向 CPU slices，再由原候选转换器构造 | 原 predict 参数、NMS/坐标恢复、候选构造、稳定顺序和 top_k；原 Results/Boxes 不修改 |
| a1+a2 | 显式组合上述两项，供独立开关理解后再测 | 与上相同 |
| a3 | unavailable，effective=a0，给出 ABI 原因 | 原 fallback NMS；不得把该回退测成 A3 收益 |

a2 的适用范围是非流式 Results list、FP32、普通六列非跟踪 Boxes、无 masks、同一 device。空结果不做打包。遇到不支持格式、打包异常时使用同一次推理的原结果，fallback_count/last_error 可见，不重复推理、不缓存旧输入。mask 几何在 a1 下也使用原 converter。

CPU slices 持有 host tensor storage，因此下一帧不会复用/覆盖上一帧；阻塞 CPU copy 完成后才返回。a2 没有异步缓冲或队列。切片保留 left/right 原顺序和每目行数，包括一目为空。返回的新 Boxes 数据在 CPU，此变更仅用于 detector 内部转换，不能未经审查扩展为通用模型预测接口承诺。

`describe()` 包含 requested/effective、available、fallback_count、last_error、predict_calls、converted_results、packed_batches/rows、d2h_calls/bytes，以及 last_pack_wall_ms / pack_wall_ms_total。pack wall 包括 cat、阻塞 copy、Python 浅拷贝，不能当作纯 GPU 传输时间。正式计时应同时记录完整检测器墙钟和该 pack 墙钟。

`restore()` 恢复安装前实例属性（原本没有实例属性时删除，恢复类方法解析），可以重复调用。如果其他代码在安装后再次替换同一挂接点，restore 会报错，防止覆盖新的钩子。协调 Agent 的临时计时钩子应先撤销再调用 restore。

## Golden 中真实候选规模

按原始 `[2,5,8400]` 的第 4 通道严格 `> 0.45` 统计，未重新执行 NMS。one-class 无其他类别列；统计不读取或改写任何冻结文件。

| 统计范围（122 目） | 总数 | 均值/目 | P50 | P95 | 最大/目 | 空目 |
|---|---:|---:|---:|---:|---:|---:|
| conf 过滤后、NMS 前 | 767 | 6.2869 | 8.5 | 18.7 | 20 | 47 |
| 原 NMS 后最终框 | 85 | 0.6967 | 1 | 2 | 2 | 47 |
| 原 top_k=5 后候选 | 85 | 0.6967 | 1 | 2 | 2 | 47 |

达到 20 个 NMS 前框的目包括 `frame_001654/right`、`frame_001521/left,right`、`frame_001682/right`、`frame_002121/left,right`；这些目原 NMS 后均为 2 框。Golden 没有密集数百框案例，也没有触发 top_k 截取，因此不能仅凭 Golden 判断极端场景正确性或 GPU 收益；测试额外构造重叠幸存框、8 框以上、同分和 top_k 场景。

## 已完成的正确性验证

本机 Python 3.8.20、Torch `2.4.1+cu121`、NumPy 1.24.4、OpenCV 5.0.0，测试仅使用 CPU tensor，未用本机 CUDA。机器人 Torch/ABI/设备不同，因此下列通过不能替代实机验证。

1. 新增 10 项 unittest 全部通过。覆盖空结果、左右不对称、重叠幸存框、相同置信度稳定顺序、负边界/半整数 Python 舍入、宽高最小 1、小目标、类别字段、None/负数/零/正数 top_k、变化输入、不改原 Results/Boxes、mask 回退、FP64/7列/stream 不支持回退、不重复 inference、默认关闭、a3 unavailable、重复安装拒绝、原实例覆盖恢复。
2. 61 对 Golden 最终框在 a0/a1/a2/a1+a2 下转换后的每一个候选字段、顺序和左右归属与 frozen golden.json 精确相同。
3. 将这 61 对 frozen 最终框注入实际 `SoccerPerceptionPipeline`，a0/a1/a2/a1+a2 共 244 对重放，按原 calibration、timestamp、config 执行真实候选选择、双目定位、tracking、ROS payload；selected、measurement、track、七字段 ROS payload 与 Golden 相同（浮点比较绝对容差 1e-12，其他字段严格）。这属于实现等价，不是 Val 物理三维真值验证。
4. 连同现有候选/定位/输出调度/跟踪回归共 36 项通过，最终运行 0.188 秒。`git diff --check` 通过。

复现（在本工作树 `soccer_perception_ros/`）：

```bash
export E04_GOLDEN_DIR=/home/misaka/workspace/experiments/E04_tensorrt_pipeline/runs/20261022T020842Z_78f1b7/collection_v1/stage0_golden_attempt1
export SOCCER_MODEL_DIR=/home/misaka/workspace/experiments/E04_tensorrt_pipeline/runs/20261022T020842Z_78f1b7/cpu_test_models
PYTHONDONTWRITEBYTECODE=1 /home/misaka/miniconda3/envs/soccer_perception/bin/python -m unittest tests.test_e04_postprocess tests.test_candidate_selection tests.test_measurement_localization tests.test_output_scheduler tests.test_pipeline_regression -v
```

不设置 E04_GOLDEN_DIR 时，硬件无关的 8 个专项仍运行，2 个 Golden 测试明确 skip。

## 性能、限制与交给协调 Agent 的验证

性能状态均为 **not_run**；没有宣称 a1、a2 或组合提升 Hz。a1 在每目平均不足一框的 Golden 上可能收益很小；a2 增加一个 cat 和浅拷贝，可能抵消同步减少，必须保留负结果。

待协调 Agent 串行、由用户启动长脚本：

- 机器人 FP32 CUDA 张量与真实 Ultralytics Results/Boxes 的 61 对 Golden 对照、变化输入、两目归属；逐项查看 fallback_count==0、packed_batches、实际 d2h_calls/bytes。
- 针对 dense/tie/empty 场景保留同一原 NMS，确认本模块没有改变输入或幸存顺序；不把“没有测试新的 NMS”写成“A3 已通过”。
- 分别 a0/a1、a0/a2，100 次预热、3×60 秒，交错复测；记录 pack 墙钟、原候选转换墙钟、完整检测器墙钟、系统 processing/publish Hz、P95/P99；确认 NMS/阈值/top_k 保持冻结值。
- 真实 B Graph/C preprocess 组合后再检查 output storage 生命周期，禁止仅凭 converter 数值降低认定优化有效。
- 机器人内存稳定性和长期运行没有在本 Agent 内执行；所有实机结果由协调 Agent 写入正式报告。

当前验收：源码边界、可回滚开关、CPU Golden/下游协议门槛通过；**实机正确性与可重复性能双重门槛尚未通过，暂不可纳入生产候选。**

## 协调补充：实机正确性回收

phase1单项实机正确性已通过：7变体各61对NPZ字节一致，语义零差异、零fallback、恢复完整；Graph 71case和161次检测器重放验证通过。A2 138次D2H/6840字节；C2单host/view各分配一次。此补充不代表正式性能或长期稳定性通过，详见CORRECTNESS_REPORT.md。

## 协调补充：28轮离线正式性能验收

A1三轮配对平均慢0.320ms，仅1/3正收益；A2平均节省2.942ms/5.030%，三轮均值/P95/P99均改善；A1+A2节省3.148ms/5.391%，相对A2增量方向不一致。A2 converter均值0.488ms、pack1.044ms，pack已在predict/完整检测器墙钟中，不重复相加。正式测量每batch48字节/1次D2H、两行最终框，计数与CSV匹配，零fallback/restore完整。A3仍不可用。

独立Agent审查记录位于对应worktree的E04_*_OFFLINE*文件；统一统计、局限与下一步以PERFORMANCE_COMPARISON.md、REPORT.md和NEXT_RUN.md为准。

## 无球system补充

21轮无球system完成：A2三轮D2H均0，仅空路径检查，processing宏变化-0.352%；A1 -0.188%、A1+A2 -0.391%。不能用这些空路径数据否定或验收有框固定图收益，需补有球单项。

## 有球单项审查与组合正确性阶段

有球21轮已复算：A2 processing宏+4.786%，publish宏+4.781%，约3ms read-ready下降且各轮P95/P99改善。D2H 919/930/930次、43824/44520/44616B；pack约1.080ms已计总wall。A1+A2三轮都不如A2；只保留A2。后验单框敏感性排除空帧主导，不对子集算Hz。

## 组合正确性已审查与正式性能准入

R4/R5的A2路径与冻结Golden全部一致；每变体predict161、打包/D2H138、285行/6840B、零回退、恢复完整。新矩阵保留同期A2，分离Graph增量，A1不再组合。

正式组合收益仍not_run，见PERFORMANCE_COMPARISON.md；回收与六份独立审查见RAW_DATA_INDEX.md。


## phase5最终组合审查与暂停

A2同期system宏+3.566%；R4对A2宏+3.246%，NMS后一次D2H/24B每行计数与CSV一致；原NMS未替换。A2本轮第3轮P99回退1.373ms，不能延续上一阶段“各尾部都改善”措辞。R4对R0同负载子集read-ready宏仍省4.405ms，测量有效率差异不足解释主要收益，但物理精度未验证。A1不保留，A3未验证。

本轮完整回收293文件，35attempt中30complete入统计、4superseded和1failed排除；独立复核见phase5/independent_reviews/E04_A_FINAL_REVIEW.md/json，所有报告以REPORT.md及PERFORMANCE_COMPARISON.md最新同phase表为准。后续暂停，不再启动测试。
