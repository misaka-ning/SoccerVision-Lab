# 结果与证据导航

[分组结果摘要](RESULTS.md)是当前研究展示入口，覆盖已有模型质量、训练预算、Engine计时、系统性能与负结果。全实验假设和状态见[实验导航](../experiments/README.md)，数字来源、冲突与缺口见[来源核对清单](../docs/SOURCE_AUDIT.md)。

|阅读目的|入口|范围|
|---|---|---|
|快速比较已有结论|[RESULTS.md](RESULTS.md)|按Val设备/阈值和实机计时边界分组；E08结果not_run|
|早期模型研究|[E01/E02报告](E01_E02_REPORT.md)|E00/E01 CPU conf0.25与E02 CUDA conf0.45分别解释|
|E00–E03逐项详表|[历史表格索引](experiment_tables/README.md)|2026-10-22阶段快照；完整路线以实验导航为准|
|nano/KD结果与修复|[E07统一报告](../experiments/E07_warmstart_distillation/REPORT.md)|E01/E05/E06/E07开发Val；零面积候选处理透明记录|
|实机瓶颈与执行负结果|[E03报告](../experiments/E03_tensorrt_profiling/REPORT.md)|旧/新Engine分组、Top20、L19、Nsight与回收校验|
|系统性能与部署边界|[E04入口](../experiments/E04_tensorrt_pipeline/README.md)|phase5性能、后续安装、MAXN筛选和未验收项分开|

[runs.csv](runs.csv)仍只有表头，是历史预留的结构化登记接口，不是完整排行榜。本次仅根据可核实报告整理文档，不在缺少全套run、模型/数据指纹时反向填造登记条目。

质量比较必须说明数据版本、Val/Test、类别映射、输入、阈值、设备和分母；速度必须说明Engine身份、设备/软件、精度、功耗/时钟、预热/重复、同步和计时范围。Val开发选择、多seed稳健性与最终Test评价分别报告；参数量/FLOPs不等于实机加速。

本目录只保存摘要及证据链接。工作站`runs/`、忽略的`experiments/eval/`及大型恢复包是**本地产物引用**，不承诺随克隆提供；公开报告与本地位置的对应关系见[复现说明](../docs/REPRODUCIBILITY.md#公开摘要与本地产物)。
