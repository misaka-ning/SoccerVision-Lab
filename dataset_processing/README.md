# 已完成的数据集审核记录

2026-10-19全部9批已由用户完成审核。此目录保留原始CSV/JSON、固定名单、label恢复备份、批准记录和最终统计；不再存放本轮审核的可执行代码。

- [最终统计](batch-review-20261016/final-statistics-20261019/REPORT.md)。
- [批次完成记录](batch-review-20261016/README.md)。
- 所有审阅代码现位于 `script/dataset-reviewer/`，一次性原始源码按原目录归入其 `history/processing-code/`；路径和SHA映射见 `reports/review-tool-cleanup-20261019/code-migration.json`。
- 审核完成后已清理可重新生成的全图拼页、ROI、候选对比图、临时UI截图及Python缓存。旧manifest中图片路径和SHA仍代表当时审阅证据，原始记录未改写；被清理的预览见 `reports/review-tool-cleanup-20261019/removed-generated-files.json`。
- 早期CSV/JSON和label备份继续保留，原图、最终label和当前metadata未改变。近期新增的 `dataset-audit-20261019/` 等其他分析工作不在本轮清理范围。
