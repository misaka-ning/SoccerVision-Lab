# 研究结果摘要：按评估口径分组

[项目首页](../README.md) · [全部实验](../experiments/README.md) · [来源核对清单](../docs/SOURCE_AUDIT.md)

本文整理已有可读报告，没有重新训练、预测、测速或读取Test图片/标注。表格保持原报告精度，不从四舍五入数值重造更精确差值。E01/E02/E05–E07部分完整run未随Git提交：可核对公开报告，不能声称本次重新验证了其全部原始输入。[产物与证据层级](../docs/REPRODUCIBILITY.md#公开摘要与本地产物)

## 共同指标定义

模型表均为冻结 **datasets/v1开发Val**：1223张、855个球框、410张确认无球图。640正方形letterbox、FP32、one-to-many+外部NMS、离线batch4、无TTA；AP候选下限0.001、IoU0.50–0.95，NMS IoU0.7、max_det300。固定工作点的P/R与误报使用匹配IoU0.5，具体conf见各组。单类AP不等于包含COCO面积/crowd规则的完整COCO评测。[定义来源](../experiments/E00_original/evaluation/REPORT.md)

无球FPR = 至少一个过工作阈值预测的无球图数 / 确认无球图数；不是FP框数除以总图片数。Small/Occluded来自图级场景标记，Recall分母为该场景图中的GT框，子集有交集。数据版本、设备或工作点不同时分表，不按表面数值排成统一名次。下文不将训练器逐轮Val当成保存后best.pt的独立Val。

## A：E00与E01历史CPU评估

范围：v1 Val；**CPU单线程**，conf=0.25，其余条件同上。只比较检测质量；评估墙钟含加载/预热等，未用于硬件速度结论。模型训练设备另见预算表。

|模型|AP50 %|AP50–95 %|Precision %|Recall %|无球误报图 / 无球图|无球FPR %|
|---|---:|---:|---:|---:|---:|---:|
|E00 原模型|60.2318|55.4108|99.4638|43.3918|0/410|0|
|E01 单类微调|96.0161|78.5508|94.9275|91.9298|19/410|4.6341|

来源：[E01/E02报告“E1完成的工作与结果”](E01_E02_REPORT.md#e1-完成的工作与结果)，E00另有[原始metrics.json](../experiments/E00_original/evaluation/metrics.json)。结论：E01改善漏检，但低阈值误报增加。任务训练和类别数同时变化，不能把收益全部归因于缩减类别数。

## B：E02独立CUDA评估

范围：v1 Val；**CUDA FP32**，conf=0.45。训练报告记录RTX4060环境，但原始评估runtime在本地run；这里不补造设备UUID、驱动或时间戳。数据内容与AP核心方法已由原报告核对，和A组仍属于跨设备历史记录，不是同环境配对复测。

|模型|AP50 %|AP50–95 %|Precision %|Recall %|无球误报图 / 无球图|无球FPR %|
|---|---:|---:|---:|---:|---:|---:|
|E02 L19缩窄|95.9545|78.7770|99.1150|91.6959|3/410|0.7317|

来源：[E01/E02报告“恢复训练后的Val精度”](E01_E02_REPORT.md#恢复训练后的-val-精度)、[E02实验表](experiment_tables/E02.md)。AP接近E01；不能将不同conf下的P/R差异解释为结构收益。E02从E01额外训练，原结构同预算control没有训练结果。硬件负结果见D组，不用参数减少代替加速证据。

## C：E01与nano/KD统一开发Val

范围：v1 Val；**报告所述RTX4060/CUDA0评估路线**，FP32、conf=0.45、batch4。E01/E05复用核验后的完整结果，E06/E07串行新评估；原始runtime与来源清单保留在本地run，本页没有重新执行。来源为[E07统一报告](../experiments/E07_warmstart_distillation/REPORT.md)、[E05报告](../experiments/E05_yolo26n/REPORT.md)、[E06报告](../experiments/E06_distillation/REPORT.md)，设备入口见[E07说明](../experiments/E07_warmstart_distillation/README.md)。

|模型|AP50 %|AP50–95 %|Precision %|Recall %|Small Recall %|Occluded Recall %|无球误报图 / 无球图|无球FPR %|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|E01-s|96.017|78.567|97.100|90.058|86.170|80.074|12/410|2.927|
|E05-n|94.165|76.846|98.907|84.678|79.787|70.111|4/410|0.976|
|E06-KD1|96.506|77.192|94.272|92.398|92.340|82.288|25/410|6.098|
|E07-WarmKD|95.265|77.540|96.754|90.643|88.511|76.015|7/410|1.707|
|E08-NoKD|not_run|not_run|not_run|not_run|not_run|not_run|not_run|not_run|

E08一行仅标待执行对照，不是该次历史评估中的模型。E08代码/离线测试/CPU合成smoke已完成，真实准备、CUDA smoke、正式训练与统一Val均not_run。[E08验证记录](../experiments/E08_warmstart_no_distillation/VALIDATION.md)

E07首次评估遇到有限零面积候选；原失败输出保留，存档评估副本保留这些候选按IoU=0计入共享指标，未丢弃候选。原报告记录四模型预测已用共享算法重算核对。不能把不同评估器准入状态默默混用；E08后续统一比较入口将另行核验完整证据。[修复说明](../experiments/E07_warmstart_distillation/REPORT.md#评估异常与透明修复)

结论是取舍，而非全面提升：E05误报少但召回低；E06困难场景召回较高，误报代价明显；E07比E06更均衡，但其相对E05增益仍包含额外训练。E05/E06同初始化，E07/E08使用E05 best且新建优化器；实际早停预算不同。没有多seed显著性或Test泛化结论。

## 训练预算

以下训练均按相应报告使用RTX4060、v1 Train4346/Val1223、seed42、640/batch8、AdamW、100轮上限和patience30。E08只有计划预算，没有真实训练。不同初始化、KD计算成本和计时范围不能当作统一训练效率赛马。

|实验|初始化 / 前置成本|本阶段实际轮数 / 最佳轮次|报告耗时|计时范围与来源|
|---|---|---:|---|---|
|E01|E00原始s权重|74 / 44|66.07分钟|原摘要未细分边界，不作精确速度比较；[E01表](experiment_tables/E01.md)|
|E02|E01 best；额外恢复训练|78 / 48|4033.39秒|训练CSV累计，不与编排墙钟混比；[E02表](experiment_tables/E02.md)|
|E05|官方nano转单类init|73 / 43|2365.742秒|训练编排墙钟；[E05报告](../experiments/E05_yolo26n/REPORT.md)|
|E06|与E05相同init，加KD|44 / 14|32.33分钟|训练编排墙钟；[E06报告](../experiments/E06_distillation/REPORT.md)|
|E07|E05第43轮best；E05完整任务另花费73轮|49 / 19|34.95分钟|仅E07训练编排墙钟，不含E05；[E07报告](../experiments/E07_warmstart_distillation/REPORT.md)|
|E08|与E07相同E05 best，新优化器|not_run|not_run|最大100轮/patience30是设计；[E08方案](../experiments/E08_warmstart_no_distillation/README.md)|

E05最终验证回调曾多计一轮，报告以CSV实际73轮为准。E08正式运行将记录实际更新次数与预算差，历史报告缺少实际optimizer更新次数时不得由“轮数×batch数”猜测。早停对照比较的是同规则下的结果，不等于固定更新次数的因果估计。

## D：E03 Engine正常计时与诊断

**数据/范围：** 正常计时使用GPU常驻、固定seed输入，不是Val/Test精度；导出正确性另外使用固定v1 Val子集。设备为Jetson Orin NX 16GB、JetPack5.1.5、TensorRT8.5.2.2、25W模式、GPU上限408MHz动态时钟。FP16 tactics、FP32 I/O，640/batch2。CUDA event包围Engine执行并逐次同步，预热100次，每模型三轮、每轮60秒交错执行；不含预处理、传输和NMS，conf不参与这个计时边界。

|构建组|E01 mean / P95 ms每batch2|E02 mean / P95 ms每batch2|结论|
|---|---|---|---|
|原有Engine|28.13498 / 28.17087|28.27537 / 28.33907|未支持E02加速|
|新performance Engine|28.17795 / 28.27449|28.22171 / 28.26188|未支持稳定结构收益；不与旧图合并|

来源：[正常计时CSV](../experiments/E03_tensorrt_profiling/results/normal_timings_summary.csv)、[E03完整报告](../experiments/E03_tensorrt_profiling/REPORT.md)。旧图L19三次profile合计1.36850→1.47933ms，增加8.10%，是**带profiler的局部范围**，不能当作正常整网耗时的精确分解。E03单轮系统锚点16.8124Hz对应另一现场且Viser开启，不与后续E04跨阶段相减。

## E：E04 phase5同期有球系统

**数据/范围：** 现场固定相机有球场景，不是完整Val/Test精度；正确性另用冻结v1 Val61对。Orin NX 16GB、TensorRT8.5.2.2、25W/408MHz上限、E01 Engine、640/batch2、FP32 I/O/FP16 tactics、conf0.45、NMS IoU0.7、top-k5、max_det300。ZED Mini VGA、Viser关闭；每作业预热100次、测60秒，三轮首尾R0，候选轮换。

|路径|processing Hz（帧对/秒）|完整cycle均值 ms|读取完成至发布 mean / P95 / P99 ms|相对同期R0的配对Hz宏平均|
|---|---:|---:|---|---:|
|R0 原路径|14.580|68.416|63.943 / 67.053 / 71.183|基线|
|A2 合并回传|15.100|66.058|61.548 / 65.131 / 71.022|+3.566%|
|R4 A2+Graph|15.590|63.973|59.491 / 62.307 / 67.033|+6.928%|
|R5 A2+Graph+C2|15.710|63.484|59.012 / 61.771 / 65.878|+7.748%|

来源：[E04性能比较](../experiments/E04_tensorrt_pipeline/PERFORMANCE_COMPARISON.md)、[阶段报告](../experiments/E04_tensorrt_pipeline/REPORT.md)。绝对值由原始帧池化，Hz按有效窗口帧数/时间计算；相对收益是三轮等权配对宏平均，不从池化均值另算。读取完成至发布不包含曝光到读取、相机队列或控制端消费；不能与Engine event相加，也不把cycle均值倒数当Hz。

保留负结果：R5相对R4第二轮processing为−0.218%，C2增量不稳定；A1不保留。R4真实相机measurement_valid略低于R0，不能据不相同帧归因于Graph，也不能说物理定位精度已验收。后续安装记录与这次性能试验分开：[A2+Graph接入](../experiments/E04_tensorrt_pipeline/integration/E01_a2_graph_20261022T103907Z/INTEGRATION_REPORT.md)。长期稳定性及新的生产场景正式性能仍未验收。

## F：E04 MAXN预处理筛选

**数据/范围：** 2026-10-23固定v1 Val61对离线回放，非相机系统A/B、非Test；Orin NX 16GB、MAXN mode0，正式段记录918MHz，TensorRT8.5.2.2、E01+A2+Graph、640/batch2、conf0.45，原NMS/定位不变。每方案100次预热，四块首尾R0交错；计时从Resize/Padding/打包至传输、转换、归一化完成就绪，含同步验证。Graph推理在范围外。

|路径|样本|输入就绪mean / P95 / P99 ms每帧对|池化平均节省 ms|决定|
|---|---:|---|---:|---|
|R0原版|800|8.411 / 9.238 / 9.443|基线|保留|
|canvas|400|8.649 / 9.233 / 9.409|−0.238|不采用|
|reuse|400|8.036 / 8.955 / 9.149|+0.375|不足预设1ms门槛且前两块无收益，不采用|

来源：[MAXN预处理完整负结果](../experiments/E04_tensorrt_pipeline/preprocess_race/20261023T014627Z/REPORT.md)。不与E组25W系统结果合并；MAXN是模式，非实测功耗。本轮未测系统Hz，未证明达到目标频率，不能用预处理毫秒倒数外推。

## 未完成或证据不齐的结论

|项目|可确认状态|缺口|
|---|---|---|
|E08无KD继续训练|实现/离线验证完成；正式流程not_run|原历史run与CUDA环境、真实训练/Val结果|
|E02原结构继续训练control|只有准备记录|正式训练和独立Val|
|nano实机四模型同条件对照|未归档完成；另有现场消息频率观察|每模型Engine SHA、有效配置、重复作业日志、计时边界|
|A2+Graph长期稳定性/物理定位精度|未验收|长稳与物理测量依据；CPU/mock不替代|
|最终Test成绩 / 独立场次泛化|本摘要无可核实模型结果|候选和阈值冻结后的正式协议与结果；现v1 Test并非独立场次|

现场观察及历史叙述冲突的完整处理见[来源核对清单](../docs/SOURCE_AUDIT.md#待补齐的证据)。本页保留负结果，未通过代码完成、数据加载PASS、模型大小或现场消息频率补造实验结论。
