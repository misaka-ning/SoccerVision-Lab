# MAXN 预处理快速赛马结果

日期：2026-10-23。运行：`offline_20261023T020353Z_32626`。**已完成，按停止条件结束本轮；保留当前 MAXN + A2 + CUDA Graph，不进行系统 A/B，不采用候选。**

## 结论

最优候选 `reuse` 的输入就绪墙钟平均仅减少 **0.375 ms/双目帧对**，未达到用户规定的1 ms门槛，且四块中前两块没有提速。仅复用Canvas反而平均慢0.238 ms。本轮得到正确性通过但性能不足的负结果。

没有进行现场系统测试，**不能宣称接近或达到25 Hz**。约23 Hz为用户此前观察，本轮未复测；不将预处理耗时倒数或输入就绪节省量充当系统Hz。若23 Hz对应43.48 ms/cycle，到25 Hz理想上仍需约3.48 ms/cycle的实际系统改善。

## 真实实现与瓶颈

原路径：OpenCV `INTER_LINEAR` Resize → 常量114 Letterbox Padding → `np.stack` → BGR/RGB与CHW视图 → 连续内存复制 → `from_numpy` → 阻塞传输 → FP32 → 除255。

50次原路径诊断的平均CPU方法墙钟：

| 操作 | ms/双目帧对 |
| --- | ---: |
| Resize，两目合计 | 5.519 |
| Padding，两目合计 | 0.234 |
| pre_transform，包含上述两项 | 5.907 |
| stack | 0.311 |
| 连续RGB/CHW打包 | 1.081 |
| to(device)，包含必要等待 | 0.964 |

Resize约占本次pre_transform方法墙钟的93.4%，是最大的可见CPU项。Canvas复用主要避免Padding输出分配及拷贝，没有消除Resize插值成本；本轮数据不支持仅靠这些缓冲改动获得所需系统收益。

诊断输入就绪均值9.415 ms，属于独立50次带分段包装的采样，不能替代下方无分段正式筛选R0的8.411 ms。Resize/Padding已包含在pre_transform，不能重复相加；异步类型转换/归一化的提交墙钟和CUDA事件跨度也不是纯kernel时间。

## 候选与正确性

| 方案 | 实现 | 正确性 |
| --- | --- | --- |
| R0 | 当前MAXN + A2 + Graph，原预处理 | 新采61对参考 |
| canvas | 左右目各一个复用Canvas，Resize写入ROI，后续原预处理不变 | 61/61通过 |
| reuse | 现成Canvas + RGB/CHW host打包复用，阻塞传输，每次独立FP32输出 | 61/61通过 |

使用既有冻结61对/122张真实Val，逐图SHA通过；已知Small28、Occluded27、Blurred22、No Ball22张，标签可重叠，未访问Test。两个候选各61对的输入shape、dtype、通道、逐元素值、原始Engine输出、全部最终框/置信度、候选顺序和左右目归属均精确一致；输入最大绝对差和差异元素数均0。坐标恢复、匹配、测量、跟踪及ROS payload/diagnostics也一致，仅排除墙钟计时字段。

共183条逐对记录含61条R0参考和122条独立候选比较。三方案测量有效37/61、跟踪有效52/61，帧级结果完全一致；这是同一冻结校准下的实现等价，不是物理定位精度或现场有效率验收。

Graph在每次加载时捕获1次，正确性每方案新增61次Replay，零回退；候选均61/61成功、零回退。Canvas分配2张，reuse分配1张Canvas/1个host/1个view，复用方案保留独立FP32输出。正确性恢复通过，任务最终cleanup通过。计时阶段8次候选hook各110次调用（10次局部预热+100正式），分配及回退计数正常；这些hook快照在restore前，未声称逐次都有after-restore快照。

VPI2.4.8可导入，但独立资格探测中CUDA和VIC的直接BGR8 Resize均返回 `VPI_ERROR_INVALID_IMAGE_FORMAT`，未进入性能组。只排除本轮无颜色格式转换的短接路径，不能概括为VPI/VIC不可用。没有临时开发NV12互操作或复杂CUDA模块。旧Torch bilinear有已知uint8差异且无现成通过验证的接线，本轮未纳入。

## 一次离线筛选

每方案100次真实图预热；4块交错首尾R0，中间两个候选顺序反转。每候选400次、R0共800次，原始CSV共1600条。范围包含Resize/Padding/打包/实际传输/转换/归一化，直到模型输入完成就绪。CUDA事件同步验证完成；CPU提交时间和事件跨度另存。每次计时后在范围外执行原Graph推理并同步，维持活动GPU负载，不把Engine执行计入预处理。

| 版本 | 样本 | Mean ms | P95 ms | P99 ms | 平均节省 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| R0 原版 | 800 | 8.411 | 9.238 | 9.443 | +0.000 |
| canvas | 400 | 8.649 | 9.233 | 9.409 | -0.238 |
| reuse | 400 | 8.036 | 8.955 | 9.149 | +0.375 |

上表分位数为各方案池化分布；准入另用每块首尾R0统计量的均值对照，不能由池化P95/P99掩盖局部退化：

| 候选 | 第1块节省ms | 第2块 | 第3块 | 第4块 |
| --- | ---: | ---: | ---: | ---: |
| canvas | -0.562 | -0.406 | +0.118 | -0.104 |
| reuse | -0.077 | -0.004 | +0.566 | +1.015 |

reuse前两块P95/P99均退化；canvas三块均值和尾部退化。基线四块首尾绝对漂移分别0.543/1.022/0.064/0.131 ms，最大漂移超过reuse平均节省量，无法据本次数据证明稳定改善。第4块单独省1.015 ms不构成总体达到1 ms。两方案均未通过预先冻结的均值/稳定性/尾延迟门槛，未选winner，也没有追加重复筛选。

## 测量环境与波动

按原始帧UTC-ns将遥测对齐到16个实际100帧段窗口（UTC 02:04:26.366～02:05:03.122，香港时间10:04:26～10:05:03），得到68个sysfs GPU频率点，全部918MHz。对完整落入测量段的秒桶取36条tegrastats，GPU温度52.062～55.687°C，未见伴随频率下降的热降频证据。不能用整个任务（初始化/正确性/预热）替代正式段的环境。

CPU各核频率/负载有变化；没有主线程驻核信息，不能将收益变号具体归因。tegrastats未输出VDD/POM功耗rails，**实际瓦数未获得**；MAXN是模式，不是实测耗电量。nvpmodel的EMC cap读取权限报错保留，未声称完整验证EMC。GR3D频率字段@[0]未用于判断，实际频率使用sysfs。

CSV及正确性另经两个Agent独立复核，与原summary一致；复核记录集中在agents/b/review.json及agents/c/offline_review.json。

## 系统对照与保留决定

- R0现场Processing/Publish Hz、Detector/cycle/读取完成至发布分布：本轮未测。
- R1与R0的三组正式系统A/B：按不足1 ms停止条件不运行。
- 是否接近25 Hz：未证明；不编造系统级数据。
- 是否采用：不采用canvas/reuse，保持当前MAXN+A2+Graph。
- 回滚：候选仅本实验进程私有hook，已恢复并退出；生产代码/YAML/Engine前后hash一致，无需改生产配置。未启动相机、ROS发布或控制测试。

## 原始证据与复现

重要原始数据保存在 `recovered/offline_20261023T020353Z_32626/`：`environment.json`、`correctness.json`、`per_pair.json`、`diagnostic.json`、`screen_frames.csv`、`summary.json`、`telemetry.jsonl`、`tegrastats.log`、`status.json`及VPI资格JSON。回收15份文件逐项SHA256通过，清单 `recovered/recovery_sha256.json`；采集时脚本/配置身份见其payload manifest和environment，原始发布包 `payload.tar.gz` 保留。

环境：Jetson Orin NX 16GB、MAXN mode0、动态GPU上限918MHz、JP5.1.5、TRT8.5.2.2、Torch2.0.0+nv23.05、Ultralytics8.3.159、OpenCV4.12；本轮OpenCV/Torch线程均8，未调整。E01 Engine SHA256：`98c1b6bc703b29874d95db94d9cf51ef5b4a4142a7ca6cf22362a0c616fbf348`。640/batch2、class0、conf0.45、原NMS/定位、A2/Graph核心不变；66份源/安装代码和YAML指纹完整。正式采集前20项本地CPU测试通过，实机预检通过。

不再启动本轮任务；保留一次筛选的负结果。没有构建Engine、升级依赖、生产安装、commit或push。
