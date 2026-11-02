# 研究展示文档来源核对清单

核对日期：2026-11-02。范围是文档、已跟踪的结果摘要和实际工具接口，未重新计算模型指标、训练、导出或实机测速，未读取Test图片/标注。

PR #1核对时为OPEN、未合并，head为`9264e4b83e3ca4cd2e4cd10adfa4ff7b5787f4ed`；本后续文档分支基于该head，保留E08文件和共享审计实现。项目约定见[AGENTS.md](../AGENTS.md)。检查结果见[DOCS_CHECKS.md](DOCS_CHECKS.md)。

## 来源与使用位置

|来源|已核对内容|展示中如何使用|
|---|---|---|
|[数据版本导航](../datasets/VERSION_INDEX.md)、[v1报告](../datasets/v1/REPORT.md)、[共享配置](../script/config.yaml)|v0/v1数量、当前选择、保留集、场次限制|首页数据表、数据工作流；只引用已有统计，不重新扫描数据|
|[E00报告](../experiments/E00_original/evaluation/REPORT.md)、[metrics](../experiments/E00_original/evaluation/metrics.json)|class32映射、v1 Val成员分母、CPU/阈值/指标与时间含义|结果A组；JSON数字与摘要交叉核对|
|[E01计划](../experiments/E01_baseline/PLAN.md)、[E01/E02报告](../benchmarks/E01_E02_REPORT.md)、[E01表](../benchmarks/experiment_tables/E01.md)|迁移来源、配方、74/44轮、CPU独立Val及66.07分钟历史记录|E01导航、结果A组及预算；耗时边界未细分，不作速度排名|
|[E02计划](../experiments/E02_c3k2/PLAN.md)、[README](../experiments/E02_c3k2/README.md)、[E02表](../benchmarks/experiment_tables/E02.md)|128→112、78/48轮、CUDA Val、4033.39秒CSV、control未完成|结果B组和预算；跨设备/阈值及额外训练限制明确|
|[E03报告](../experiments/E03_tensorrt_profiling/REPORT.md)、[正常计时CSV](../experiments/E03_tensorrt_profiling/results/normal_timings_summary.csv)、[L19表](../experiments/E03_tensorrt_profiling/results/l19_comparison.csv)|正常event边界、旧/新组、profile局部负结果、系统单轮锚点|结果D组；CSV四行对照报告，三种计时不混算|
|[E04报告](../experiments/E04_tensorrt_pipeline/REPORT.md)、[性能表](../experiments/E04_tensorrt_pipeline/PERFORMANCE_COMPARISON.md)|25W同期R0/A2/R4/R5、三轮宏平均、读完至发布范围、负结果|结果E组与首页结论；不从池化Hz重造配对百分比|
|[E04接入](../experiments/E04_tensorrt_pipeline/integration/E01_a2_graph_20261022T103907Z/INTEGRATION_REPORT.md)、[安装指针](../experiments/E04_tensorrt_pipeline/integration/CURRENT_INTEGRATION.json)、[捕获说明](../experiments/E04_tensorrt_pipeline/integration/runtime_capture_20261023T013041Z/REPORT.md)|后续安装已完成，production_started=false，新增说明仅本地核验|更正导航中的“从未安装”印象；不写成生产实测/长稳通过|
|[E04 MAXN筛选](../experiments/E04_tensorrt_pipeline/preprocess_race/20261023T014627Z/REPORT.md)|918MHz测量段、四块、预处理计时边界、0.375ms不足门槛|结果F组独立呈现，不采用候选，系统A/B未执行|
|[E05报告](../experiments/E05_yolo26n/REPORT.md)、[初始化说明](../experiments/E05_yolo26n/PRETRAINED.json)|官方nano来源、73/43轮、2365.742秒、独立Val与最终回调计数差异|结果C组交叉核对及预算；不把progress74当实际轮数|
|[E06报告](../experiments/E06_distillation/REPORT.md)|与E05同init、KD方法、44/14轮、32.33分钟、误报取舍|结果C组及预算；保留单seed与早停差异|
|[E07报告](../experiments/E07_warmstart_distillation/REPORT.md)、[入口](../experiments/E07_warmstart_distillation/e07.py)|四模型完整Val表、场景Recall、49/19轮、34.95分钟、零面积准入修复、CUDA0默认评估路线|结果C组采用报告原精度；设备表述限定于报告/入口证据，不声称重验本地runtime|
|[E08设计](../experiments/E08_warmstart_no_distillation/README.md)、[VALIDATION.json](../experiments/E08_warmstart_no_distillation/VALIDATION.json)、[DERIVATION](../experiments/E08_warmstart_no_distillation/DERIVATION.json)|仅distill_model禁用、同E05 best、CPU合成检查、正式流程not_run|首页/导航/结果表保持not_run；不改写PR #1的实现或验收事实|
|[已有综合报告](机器人足球视觉感知系统模型优化与部署性能阶段成果报告.md)|模型叙述、消息频率观察、尚缺正式系统配对|保留原文并加证据分级补注；未绑定的观察不进入正式表|
|[工具索引](../script/README.md)、[训练解析](../script/model-training/train.py)、[评估CLI](../script/model-evaluation/evaluate.py)、[配置读取](../script/common/dataset_config.py)|实际工具职责与参数，dry-run的不同读取范围|首页Mermaid、复现命令与人工审核文档；不画不存在的自动流水线|

新结果表的数字均落在上述来源对应段落/表格；数值抽取比对及来源SHA另见[检查记录](DOCS_CHECKS.json)。历史报告中的run、图片和权重引用不因文档重排迁移。

## 状态冲突的处理

|表面冲突|来源时间与解释|采用的表述|
|---|---|---|
|E06/E07旧说明与已完成结果|准备入口仍保留手动启动说明；2026-10-23报告已补正式结果|新增README状态导航，旧命令用于新run，训练/Val已完成|
|E04“未安装”与安装记录|主实验暂停快照早于`E01_a2_graph_20261022T103907Z`接入|按phase/接入/捕获说明/MAXN筛选分段；保留原报告，仅加日期导航补注|
|E05“不能判断召回/尚无E06精度”|回收阶段叙述后已追加独立Val，随后E06/E07完成|标为历史阅读顺序，不删除原修复记录或更改数值|
|E01“官方预训练”与实际来源|综合叙述简化；计划/参考资产记录为已有E00权重|主页采用可核实的“已有E00权重迁移”，不扩写其完整训练史|
|旧权重曝光unknown与维护者确认|v1封存记录早于2026-10-19的具体SHA确认|链接[维护者确认](../reports/workspace-organization/OWNER_ASSERTIONS.md)，仅适用于该具体权重，不外推Val或其它权重|
|E08代码完成与实验完成|PR #1验证了工程接线，但正式数据run和CUDA不可用|明确真实prepare/smoke/train/Val均not_run，保留下一步命令|

只给报告添加导航/证据等级补注和修正不可访问链接；原数值、历史报告主体、代码、数据、模型、配置和原始证据保持。

## 待补齐的证据

这些缺口直接标注，不要求读者提供材料后才能阅读仓库，也不以猜测补齐。

- **E01/E02/E05–E07的完整run：** 部分权重已发布，但训练CSV、原始评估manifest、逐图预测和有效配置仍是本地引用。本次按公开报告核对，没有重验所有原始hash或数值。位置见[本地产物表](REPRODUCIBILITY.md#公开摘要与本地产物)。
- **E08正式对照：** 实现与合成CPU检查完成，真实Train/Val准备、CUDA/AMP smoke、训练及新统一Val为not_run；不能从E07历史表推断E08结果。
- **E02原结构继续训练control：** 只有准备记录，不能把候选相对原E01的AP变化全部归因于缩窄。
- **E07现场消息频率：** 综合报告记录E01约22Hz、E07在25W约30–31Hz、MAXN约33Hz；MAXN预处理报告还提到用户此前约23Hz观察。没有找到与这些观察完整绑定的Engine/有效配置/时间窗口/重复日志，E07实验报告也尚未归档正式部署验收。保留为`reported_observation / evidence_incomplete`，不纳入模型速度表，不写成重新核实的事实或稳定达标。
- **功耗与跨现场对照：** 25W/408MHz和MAXN/918MHz各有阶段记录，但不是统一场景的功耗档位A/B；MAXN筛选未取得实测瓦数。不同场次、可视化和负载下Hz不能拼成优化曲线。
- **部署验收：** A2+Graph接入安装及CPU/mock检查有记录；该次production_started=false，不能由安装成功推出CUDA生产性能、长期稳定或物理定位准确度。nano四模型统一实机比较未归档完成。
- **Test与泛化：** 未发现可用于本摘要的正式模型Test结果；已有数据加载校验不是模型成绩。v1留出与Train同场次，独立场次泛化尚无结论。
- **结构化登记和许可：** `benchmarks/runs.csv`只有表头，不能替代完整结果索引；尚未声明统一仓库许可证，数据/权重存在于版本库不等于可自由再分发。

本次未移动冻结实验、数据、权重或历史证据。完整修改范围、链接检查和E08基线保留检查见[验收记录](DOCS_CHECKS.md)。
