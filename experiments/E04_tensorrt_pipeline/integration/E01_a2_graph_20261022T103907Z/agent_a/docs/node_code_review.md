# ROS 感知节点代码审查记录

记录日期：2026-10-15。

主要来源文件：`soccer_perception_ros/soccer_perception/ros/node.py`。

行号已随 2026-10-15 的配置拆分更新，包含已补充的中文注释；后续修改代码后，行号可能变化。本文记录问题和建议，相关代码尚未修复。

## 1. 参数类型转换较宽松，部分非法数值未被提前拒绝

**来源文件**：`soccer_perception_ros/soccer_perception/ros/node.py`。

**函数及行号**：

- `_parameter_scalar()`，第 78–84 行：相机可选整数分支提前调用 `int(value)`。
- `_parameter_scalar()`，第 99–103 行：普通数值分支检查布尔值后，直接进行整数或浮点转换。
- `config_from_ros_params()`，第 135–141 行：当前显式的有限性和范围检查针对输出频率、短时漏检容错窗口。

代码定位：[相机参数转换](../soccer_perception_ros/soccer_perception/ros/node.py#L78)、[普通数值转换](../soccer_perception_ros/soccer_perception/ros/node.py#L99)、[配置范围检查](../soccer_perception_ros/soccer_perception/ros/node.py#L135)。

**问题说明**：

整数转换会截断小数；相机参数分支绕过了后面的布尔值拒绝逻辑；浮点转换本身允许 NaN 和无穷值。对 `_parameter_scalar()` 进行独立调用时，已确认以下结果：

| 参数 | 输入 | 转换结果 | 问题 |
| --- | --- | --- | --- |
| `yolo_top_k` | `3.8` | `3` | 小数被静默截断 |
| `zed_gain` | `True` | `1` | 布尔值被当作相机数值 |
| `det_conf` | `NaN` | `NaN` | 非有限值通过转换 |

这些例子验证的是转换函数本身的行为，不表示每种输入都能通过实际 ROS 参数声明阶段；部分类型不匹配也可能由 ROS 提前拒绝。

**可能影响**：

错误的 YAML 值可能被悄悄改成其他数值，或进入后续模型、筛选与跟踪处理，导致行为偏离配置意图，或者到较晚阶段才报错。

**建议**：

- 整数参数拒绝带小数部分的值，避免静默截断。
- 相机整数参数也先拒绝布尔值，再做整数转换。
- 对需要有限值的浮点参数统一执行有限性检查。
- 为置信度、输入尺寸、候选数量等增加各自的合法范围检查，并保留 `unchanged`、`-1` 等已有特殊值语义。

## 2. 位置消息使用发布时间，不能直接代表采图或测量时间

**来源文件**：`soccer_perception_ros/soccer_perception/ros/node.py`。

**函数及行号**：

- `RosBallStatePublisher.publish()`，第 255–256 行：获取发布时刻的 ROS 时间。
- `_point_from_payload()`，第 345–348 行：将该时间写入 `PointStamped.header.stamp`。
- `run_ros_node()`，第 414、421–424 行：先完成感知处理，再整理数据并等待输出。

代码定位：[获取发布时间](../soccer_perception_ros/soccer_perception/ros/node.py#L255)、[写入消息时间戳](../soccer_perception_ros/soccer_perception/ros/node.py#L345)、[处理与等待顺序](../soccer_perception_ros/soccer_perception/ros/node.py#L414)。

**关联来源文件**：`soccer_perception_ros/soccer_perception/adapters/zed.py`，第 173–174 行。流水线的帧时间戳来自 `time.perf_counter() - self._start`，是相机输入源启动后的相对计时，并非 ROS 时间。

代码定位：[帧相对时间戳](../soccer_perception_ros/soccer_perception/adapters/zed.py#L173)。

**问题说明**：

图像经过采集、检测、定位、跟踪和输出等待后，位置消息才被发送，但消息头记录的是发送时的时间。例如数据处理及等待累计耗时 80 ms，下游仍可能将这个位置理解为“当前时刻的位置”。

**可能影响及适用条件**：

如果下游把 `header.stamp` 当作测量时间，用于数据过期判断、与其他传感器同步或运动补偿，会低估数据年龄。若接口明确约定该字段表示发布时间，则这是需要明确记录的时间语义限制。

**建议**：

- 明确区分采图时间、处理完成时间和发布时间。
- 需要按测量时间处理时，保存采图时间，并建立与 ROS 时间的一致映射。
- 不要将当前的相对秒数直接写入 ROS 时间戳；需要明确两种时钟的起点和映射关系。
- 用已知处理延迟验证下游看到的数据年龄是否符合预期。

## 3. 清理阶段异常可能覆盖原始错误，或阻止后续清理

**来源文件**：`soccer_perception_ros/soccer_perception/ros/node.py`。

**函数及行号**：

- `run_ros_node()`，第 438–446 行：`finally` 中直接关闭流水线并记录停止日志。
- `main()`，第 469–474 行：先销毁节点，再检查并关闭 ROS 上下文。

代码定位：[流水线清理](../soccer_perception_ros/soccer_perception/ros/node.py#L438)、[节点与上下文清理](../soccer_perception_ros/soccer_perception/ros/node.py#L469)。

**问题说明**：

`finally` 能保证执行清理代码，但不能保证清理调用一定成功。如果检测过程先抛出异常，随后 `pipeline.close()` 又抛出异常，向外传播的主要异常会变成清理错误；原始错误通常仍保留在 Python 异常链中，但更难从主要错误日志定位。

另外，`pipeline.close()` 抛错会跳过后面的停止统计日志；`ros_node.destroy_node()` 抛错会跳过后面的 `rclpy.shutdown()`。

**可能影响**：

故障原因不容易定位，部分后续清理步骤也可能无法执行。这是异常路径上的稳健性风险，尚未在相机实机故障场景中复现。

**建议**：

- 分别记录运行阶段与清理阶段的异常，保留原始运行故障信息。
- 使用适当的嵌套 `try/finally`，让节点销毁失败时仍有机会关闭上下文。
- 增加“处理失败且关闭失败”“节点销毁失败”等异常路径测试。

## 4. 两条发布路径重复构造状态数据，存在维护成本

**来源文件**：`soccer_perception_ros/soccer_perception/ros/node.py`。

**函数及行号**：

- `RosBallStatePublisher.publish()`，第 269–299 行：构造基础状态并添加诊断字段。
- `RosBallStatePublisher.publish_status_only()`，第 313–341 行：重复构造大部分相同状态与诊断字段。

代码定位：[完整发布路径](../soccer_perception_ros/soccer_perception/ros/node.py#L269)、[仅状态发布路径](../soccer_perception_ros/soccer_perception/ros/node.py#L313)。

**问题说明与影响**：

两条路径都包含有效性、坐标约定、跟踪模式、测量状态、短时漏检容错和输出频率等字段。以后新增或修改字段时，需要同步修改两处，否则可能造成不同发布路径的状态格式不一致。

这是维护性改进项，当前重复本身不代表已经发生功能错误。

**建议**：

提取公共状态构造函数，集中生成基础字段和诊断字段；保留 `dropped_json`、`publish_invalid_position` 等路径特有字段，并分别验证两条路径的输出。

## 验证范围

- 已静态检查节点主循环、发布器、参数转换及相关相机时间戳来源。
- 已独立调用参数转换函数，确认第 1 项列出的三种转换行为。
- 此前尝试运行相关测试时，默认 Python 缺少 `yaml`，系统 Python 缺少 `numpy`，测试未能完成。
- 尚未进行 ROS、GPU 和相机实机验证；本文不将条件性风险表述为已发生的实机故障。
