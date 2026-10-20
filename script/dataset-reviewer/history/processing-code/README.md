# 已完成审核的历史处理源码

这里保留了原 `dataset_processing/` 下134份 Python/C++ 审核过程源码，按原相对目录归档。迁移时未改写其内容。原路径和新路径及源文件SHA256见 `reports/review-tool-cleanup-20261019/code-migration.json`。

这些文件包含当时的一次性预审笔记、候选框分析、截图生成、批准核验和统计脚本；它们的原始路径、输入哈希、阶段性数据假设均代表历史状态。它们不是当前运行入口，尤其不要直接执行 `reset_and_batch.py`、旧 `apply_precheck.py` 或历史批次重置脚本，以免重置已经完成的人工审核。临时预览图已在审核完成后清理，部分历史脚本的图片输入不再存在。

日常使用 [review_dataset.sh](../../review_dataset.sh)，按固定名单浏览使用 [review_football_batch.sh](../../review_football_batch.sh)。仍需维护的安全批准/预审应用工具位于 [maintenance](../../maintenance/README.md)，它们已更新项目定位和Qt锁程序路径；测试位于 `tests/`。

历史审核CSV/JSON、固定名单、label备份、最终统计与批准记录继续保存在原来的 `dataset_processing/` 中，以保持审计材料的来源和原始内容。
