# E03 结果索引

运行 `20261021T080741Z_824b47`。原始包与 625 个文件 SHA256 均通过；本机仅做 CPU 分析。实验结论、边界与下一轮优先级见 [REPORT.md](../REPORT.md)。

| 结果 | 文件 |
|---|---|
| 模块占比、L19 与图 | [模块 CSV](module_costs.csv)、[L19 CSV](l19_comparison.csv)、[PNG](module_costs.png)、[PDF](module_costs.pdf) |
| Top20：旧图时间与新图实际 shape/dtype/tactic | [完整说明及四张表](TOP20.md)、[E01 detailed](E01_baseline_top20.csv)、[E02 detailed](E02_c3k2_top20.csv)、[E01 旧图](LEGACY_E01_baseline_top20.csv)、[E02 旧图](LEGACY_E02_c3k2_top20.csv) |
| L19 逐层配对 | [配对 CSV](L19_layer_pairs.csv)、[E01 detailed](E01_baseline_L19.csv)、[E02 detailed](E02_c3k2_L19.csv) |
| 正常计时与 trtexec | [逐轮 CSV](normal_timings.csv)、[JSON](normal_timings.json)、[摘要 CSV](normal_timings_summary.csv)、[trtexec](trtexec_timings.json) |
| 三次 profile 模块原汇总 | [旧图](LEGACY_profile_summary.json)、[新 detailed](profile_summary.json) |
| Nsight 重算摘要与方法区间 | [trace JSON](trace_summary.json)、[方法重叠 CSV](detector_phase_overlap.csv) |
| CUDA API | [Engine](legacy_steady_api.csv)、[Graph](legacy_graph2_api.csv)、[检测器](detector_steady_api.csv) |
| 最长无 GPU 活动间隔 | [Engine](legacy_steady_longest_gaps.csv)、[Graph](legacy_graph2_longest_gaps.csv)、[检测器](detector_steady_longest_gaps.csv) |
| 正确性、构建与校验 | [64 Val](correctness_summary.json)、[构建清单](build_inventory.json)、[验证摘要](verification.json) |

CSV 是 UTF-8 BOM，支持常见表格软件。正常计时单位是 ms/batch2；profile 百分比基于同一 artifact 的层均值合计。Nsight 为挂载采集工具的时间线，不能当作正常系统延迟；无 GPU 活动只表示目标应用，CUDA API 墙钟与 GPU 活动重叠。

旧 Engine 在构建时只保存 layer_names_only，内部 tensor/tactic 不可得；新 detailed 表保留实际 Inspector 数据，不将其代填进旧图。首次不完整 Graph trace 保留为质量失败记录，使用 legacy_graph2 支撑主要结论。

大型原始文件在 `../runs/20261021T080741Z_824b47/`；其 `result_bundle.tar.gz` 是已校验、未改写的机器人完整归档。分析代码为 `../analyze.py`，没有调用本机 GPU 推理。
