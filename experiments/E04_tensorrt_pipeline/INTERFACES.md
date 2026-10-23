# E04 公共接口与子 Agent 边界

状态：E04-0 的正式采集和协调验收已通过，三份独立 worktree 已完成 A/B/C 首版并通过CPU集成回归，单项GPU正确性已通过，进入正式性能准备；机器人测试仍由协调 Agent 统一排程并交给用户运行。

## 公共语义

- 一批严格对应同一时刻的左、右 BGR 图，顺序固定为 left/right，不改变原始帧标识和时间戳关联。
- 模型输入固定 FP32 `[2,3,640,640]`；模型原始输出固定 FP32 `[2,5,8400]`。原始 Engine 文件和检测类别不变。
- 使用原路径实际有效的 letterbox、缩放、归一化和坐标恢复；不按版本文档假定默认值。
- 保留 one-to-many 的原 NMS、置信度、IoU、top-k、生效顺序和候选排序。阈值从实际配置/对象冻结，不从历史摘要补填。
- 输出必须保留每目归属、候选字段/顺序、双目匹配输入、定位结果、跟踪与 ROS 序列化协议。
- 任何缓冲区复用或 Graph 输入更新都必须等待上一批使用完成；不得用旧图冒充新图，不引入隐藏积压。

## 文件与职责

| 所有者 | 专有修改范围 | 不得修改 |
|---|---|---|
| A | 新增后处理/NMS/结果回传模块、A 专属正确性测试及 A 报告 | Graph、预处理、公共集成入口、生产依赖 |
| B | 新增 Engine 执行/Graph 模块、B 专属测试及 B 报告 | 后处理语义、letterbox、原 Engine、公共集成入口 |
| C | 新增预处理/数据缓冲模块、C 专属测试及 C 报告 | NMS、Engine、公共集成入口、输入尺寸 |
| 协调 Agent | 公共配置、数据协议、benchmark、Golden、集成入口、代码审查、最终报告 | 不覆盖生产模型或改动控制逻辑 |

具体文件名以已审计的部署布局为准；不得凭此表虚构已有接口或创建重复的已生效 Graph。

## 运行矩阵

开关维度独立：后处理变体 A0/A1/A2/A3、执行变体 B0/Graph、预处理变体 C0/候选。默认全部为原实现；每轮记录有效开关与实际生效/回退状态。捕获失败、执行失败或不支持输入必须可观测，不能把回退性能记成 Graph 性能。

Agent 可在自己的 worktree 运行短 CPU 单测。机器人 GPU、相机和 ROS 测试只由协调 Agent 排程并交给用户运行统一脚本。禁止子 Agent 自行 SSH 跑 GPU benchmark；禁止并行修改生产文件。

组合前要求各变体独立的 Golden 对照与至少三轮可重复性能证据。新 GPU Resize 的数值差异必须量化到检测和三维结果；只看到图像相似不算通过。A3 需先提供版本/ABI 兼容诊断，隔离验证，不全局升级 Torch/Torchvision/CUDA。

## 已冻结的实际挂接点

基线适配器为 `soccer_perception_ros/soccer_perception/adapters/yolo.py` 中的 `YoloBallDetector.detect_candidates_batch(frames, top_k)`；原始候选转换为 `_result_to_candidates(result, top_k)`。预处理/后处理对象是 `detector.model.predictor`；TensorRT 对象是 `detector.model.predictor.model`，当前 forward 使用 execute_v2。

每个候选模块约定 `install(detector, variant) -> handle`，在 predictor/backend 初始化完成后、正式预热/计时前由协调 Agent 调用。handle 提供 `describe() -> dict` 和 `restore()`；记录 requested/effective、fallback_count、last_error，Graph 另记 capture/replay/input-update 次数。原实现引用必须可恢复，不能静默把 fallback 当作启用结果。

- A 专有文件：`soccer_perception_ros/soccer_perception/optimizations/postprocess.py` 与 `tests/test_e04_postprocess.py`。改动仅限实例内结果转换/后处理，不全局改 site-packages 或替换算子。必须保留 NMS 前后顺序、六个转换入口的语义及 top-k 在候选构造后的生效顺序。
- B 专有文件：`soccer_perception_ros/soccer_perception/optimizations/graph.py` 与 `tests/test_e04_graph.py`。只挂接 backend 执行；输入是当前批次 FP32 CUDA tensor，输出保持原 backend 返回的 FP32 tensor，形状 `[2,5,8400]`。不触及 NMS/候选排序。
- C 专有文件：`soccer_perception_ros/soccer_perception/optimizations/preprocess.py` 与 `tests/test_e04_preprocess.py`。只挂接 predictor.preprocess；输出固定 FP32 CUDA `[2,3,640,640]`，连续内存，左右顺序保持。LetterBox 语义以当前 pre_transform 为准。

共享 `optimizations/__init__.py`、公共配置与适配器由协调 Agent 创建/修改；子 Agent 不修改这些共享文件。报告先写各自 worktree 的 `E04_AGENT_A_REPORT.md` / B / C，协调 Agent 审阅后汇入正式实验目录。
