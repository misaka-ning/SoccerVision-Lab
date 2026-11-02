# 实验路线与统一导航

[项目首页](../README.md) · [分组结果摘要](../benchmarks/RESULTS.md) · [复现与本地产物](../docs/REPRODUCIBILITY.md) · [来源核对](../docs/SOURCE_AUDIT.md)

截至2026-11-02，现有编号为 **E00–E08**。下面的状态区分模型训练、独立Val、工程检查和部署验收；计划、预检报告中的“未运行”属于当时记录，后续完成情况以注明日期的结果报告为准。`not_run`表示该项尚未执行，证据缺失则另写“未归档/待核验”，不互相替代。

## 全部实验

|编号与入口|假设/问题|实际改动|当前状态|主要结论与局限|可公开阅读的证据|
|---|---|---|---|---|---|
|[E00 原模型](E00_original/README.md)|已有模型的足球检测能力如何？|不训练；原80类中选择class32映射football|完整Val完成；本阶段无新增训练|conf0.25下保守、漏检多；不是单类微调结果|[评估报告](E00_original/evaluation/REPORT.md)、[指标](E00_original/evaluation/metrics.json)、[实验表](../benchmarks/experiment_tables/E00.md)|
|[E01 单类微调](E01_baseline/README.md)|足球任务微调能否改善漏检？|从E00迁移为YOLO26s单类，全网络微调|训练74轮/最佳44轮；独立Val完成|AP/召回改善，低阈值误报增加；类别和训练同时变化|[计划](E01_baseline/PLAN.md)、[E01/E02报告](../benchmarks/E01_E02_REPORT.md)、[实验表](../benchmarks/experiment_tables/E01.md)|
|[E02 L19缩窄](E02_c3k2/README.md)|减少局部宽度能否保精度、降延迟？|E01起点，L19隐藏128→112，确定性通道迁移后重建优化器|候选训练78轮/最佳48轮、独立Val及Orin比较完成；原结构继续训练control只有准备记录|整体AP接近；无可测量加速；额外训练效应未分离|[计划](E02_c3k2/PLAN.md)、[迁移预检](E02_c3k2/PRECHECK_REPORT.md)、[结果](../benchmarks/E01_E02_REPORT.md)、[E03复测](E03_tensorrt_profiling/REPORT.md)|
|[E03 TensorRT剖析](E03_tensorrt_profiling/README.md)|为何E02未提速，实际成本在哪里？|旧/新Engine分组计时、逐层profile、Nsight、系统锚点|测量、回收和本机分析完成|L19局部变慢；成本分散，系统回传/同步值得研究；诊断不是生产加速|[报告](E03_tensorrt_profiling/REPORT.md)、[结果索引](E03_tensorrt_profiling/results/README.md)、[校验摘要](E03_tensorrt_profiling/results/verification.json)|
|[E04 推理链路](E04_tensorrt_pipeline/README.md)|保持检测语义，减少回传/提交/预处理开销是否有效？|A2合并回传、Graph；缓冲与Canvas候选单独检查|phase5性能/Golden完成；后续A2+Graph接入安装；MAXN预处理筛选结束；长稳与生产验收未完成|同期25W组合收益成立；C2系统增量不稳，MAXN筛选不采用候选；不可跨阶段混比|[阶段性能](E04_tensorrt_pipeline/PERFORMANCE_COMPARISON.md)、[接入记录](E04_tensorrt_pipeline/integration/E01_a2_graph_20261022T103907Z/INTEGRATION_REPORT.md)、[MAXN负结果](E04_tensorrt_pipeline/preprocess_race/20261023T014627Z/REPORT.md)|
|[E05 nano基线](E05_yolo26n/README.md)|更小模型的质量损失与误报取舍如何？|官方nano预训练转单类，沿用E01配方|训练73轮/最佳43轮、独立Val完成；正式导出/Orin测量未归档完成|比E01召回/AP低，无球误报少；两者初始化经历不同|[报告](E05_yolo26n/REPORT.md)、[初始化来源](E05_yolo26n/PRETRAINED.json)|
|[E06 KD1](E06_distillation/README.md)|同nano起点的特征蒸馏能否恢复召回？|E05原始init，冻结E01-s教师，P3/P4/P5特征蒸馏dis6|训练44轮/最佳14轮、独立Val完成；部署验收未归档完成|Small/Occluded召回恢复，误报增加；单seed、实际早停预算不同|[报告](E06_distillation/REPORT.md)、[统一四模型结果](E07_warmstart_distillation/REPORT.md)|
|[E07 WarmKD](E07_warmstart_distillation/README.md)|用已微调nano作为KD起点是否更均衡？|从E05 best第43轮开始，重新建立优化器；教师/配方同E06|训练49轮/最佳19轮、独立Val完成；实机正式对照待核验|AP/误报较E06均衡；相对E05收益混合额外训练和KD；现场观察不是正式测速|[报告与零面积修复](E07_warmstart_distillation/REPORT.md)、[来源](E07_warmstart_distillation/DERIVATION.json)、[证据缺口](../docs/SOURCE_AUDIT.md#待补齐的证据)|
|[E08 NoKD继续训练](E08_warmstart_no_distillation/README.md)|E07增益中有多少来自额外训练？|相同E05 best与E07配方，仅distill_model=null；新优化器|实现/离线验收/CPU合成smoke完成；真实prepare、CUDA smoke、训练及统一Val均not_run|尚无实验质量或速度结论；不能把代码完成当成对照完成|[设计与命令](E08_warmstart_no_distillation/README.md)、[验证记录](E08_warmstart_no_distillation/VALIDATION.md)、[来源哈希](E08_warmstart_no_distillation/DERIVATION.json)|

E01/E02/E05/E06/E07的训练轮数来自各自结果报告，不从最终验证回调或模板上限推算。E05 best经历43轮，但整个E05任务耗费73轮；E07/E08的继续训练预算应另外记录。[预算表](../benchmarks/RESULTS.md#训练预算)

## 路线如何衔接

E00/E01建立任务基线；E02尝试小范围结构改变，E03解释实机负结果；E04据此研究系统路径。另一条模型路线由E05建立nano基线：E06从与E05相同的初始权重蒸馏，E07从E05最佳权重蒸馏，E08提供与E07同起点、同配方的无蒸馏对照。

E04不是新增检测模型；其历史25W性能、后续安装、MAXN预处理筛选分别归档。综合报告中后来的现场消息频率观察单列为未完整绑定证据，不覆盖已经核验的实验结果。E00–E03旧表仍保留在[历史实验表格](../benchmarks/experiment_tables/README.md)，全量导航以本页为准。

## 每次运行与证据约定

- 一个实验ID管理同一研究假设，一个独占新建的 `runs/<UTC>_s<seed>_<suffix>/` 管理一次运行。目录已存在就停止，不覆盖best.pt、last.pt、results.csv。
- 设计保存计划、架构/配置或其引用；训练与指标复用共享工具，不复制正式训练循环或AP实现。通用工具的默认递增目录行为不替代实验入口的隔离约束。
- 每个run记录模型来源SHA、数据版本与内容哈希、请求/有效配置、源码状态、环境、实际训练预算和恢复事件。未执行项保持null/not_run，没有部署测量时不填假0。
- `datasets/v1`只按冻结成员和SHA引用，不为每个实验复制图片。新的初始化须记录自己的曝光史，不能套用其他权重的确认。
- Val用于开发/选择；Test只能在候选与阈值冻结后另行正式评价，每次访问留痕。同场次留出与独立场次结果分开解释。
- 参数/FLOPs记录输入、工具及乘加口径；部署记录Engine哈希、设备/软件、精度、功耗/时钟、warmup、同步和计时边界。离线评估吞吐不等于机器人Hz。
- 完成后冻结run事实，订正追加记录；配置、结构或数据变化时新建run，不回写历史哈希。

权重、日志、大型原始包和本机生成配置按项目规则保留本地，公开摘要放在实验目录及[benchmarks](../benchmarks/README.md)。`runs/`路径写作本地产物引用，不能作为GitHub可访问链接。[产物定位与可复现范围](../docs/REPRODUCIBILITY.md#公开摘要与本地产物)
