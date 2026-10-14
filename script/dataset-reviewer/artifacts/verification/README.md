# 核验证据

- `history/`：原 `script/review_dataset_verification/` 完整迁移而来，包括初次核验和 `manual-label-edit/` 的后续核验。保留原文件内容、旧路径和样本统计。
- `latest/`：本次或后续运行生成的测试日志、截图、`smoke.json` 与迁移核验报告；可重新生成，不纳入版本管理。

历史报告代表生成时的数据和程序状态，不能代替当前测试结果。生成新证据的命令与判断标准见 [开发与验证](../../docs/development.md)。
