# E01：YOLO26s 单类别足球微调

训练run `20261019T092432Z_s42_853c4a` 已完成训练和独立Val。已有E00权重迁移为足球单类后微调；AP与召回改善，同时保留低工作阈值误报增加的结论。类别数和训练同时改变，不能把全部收益归因于类别数。

网页可读入口：[实验计划](PLAN.md)、[E01/E02报告](../../benchmarks/E01_E02_REPORT.md)、[E01实验表](../../benchmarks/experiment_tables/E01.md)、[按口径分组的结果](../../benchmarks/RESULTS.md)。训练编排使用[e01.py](e01.py)，复用共享Trainer；后续E02和E03分别研究结构改变及实机成本。

以下是**本地产物引用，不随Git提供**：`runs/20261019T092432Z_s42_853c4a/`中的`RESULT.md`、`E00_VS_E01.md`、`REPRODUCE.md`、`evaluation/metrics.json`及训练权重/日志。保留这些文件的工作站可继续核验原始证据；普通访客通过上述报告阅读摘要。[复现要求与定位](../../docs/REPRODUCIBILITY.md#公开摘要与本地产物)
