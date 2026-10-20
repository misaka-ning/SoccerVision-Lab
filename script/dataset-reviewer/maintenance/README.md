# 审核维护工具

日常看图、改框、场景审核和导出使用上一级的 `review_dataset.sh`。这里集中保留有安全校验的维护代码，代码与输出记录分开：

| 文件 | 用途 |
| --- | --- |
| `review_paths.py` | 定位工作空间、历史记录与Qt锁程序 |
| `audit_io.py` | 保留CSV原始行/BOM/换行、校验label、原子写入及锁协议 |
| `approve_reviewed_batch.py` | 用户明确完成一批后，从新鲜快照记录双项已审核；不改图片、框或场景 |
| `apply_precheck.py` | 校验快照与人工修改冲突后应用候选，仍保留双项待审 |
| `compact_metadata_backups.py` | 无损归档旧CSV自动备份，逐文件SHA256校验后清理旧散文件，保留最近若干份 |

`approve_reviewed_batch.py`、`apply_precheck.py` 默认只做只读计划，显式 `--apply` 才写入；沿用GUI的Qt `QLockFile`，遇到来源、字段或label变化时保留人工结果。批次输入及审计输出仍位于工作空间的 `dataset_processing/`，不会写到源码目录。每次人工确认都显式传入真实的 `--review-date YYYY-MM-DD`。

Qt锁程序源码为 `../src/qt_review_lock_runner.cpp`，随同GUI统一构建到 `../build/release/qt_review_lock_runner`。运行维护写入命令前先执行：

```bash
./script/dataset-reviewer/review_dataset.sh --build-only
python3 -B script/dataset-reviewer/maintenance/approve_reviewed_batch.py --help
python3 -B script/dataset-reviewer/maintenance/apply_precheck.py --help
```

## 自动备份归档

依赖本机 `zstd`，单线程压缩。以下命令从仓库根目录执行。默认只打印计划，以下第一条不会创建归档或删除文件；添加 `--apply` 后才归档并清理：

```bash
python3 -B script/dataset-reviewer/maintenance/compact_metadata_backups.py \
  --dataset datasets \
  --archive-dir dataset_archives/下一次备份归档目录 \
  --keep 10
```

只处理 `.metadata-review-backups/metadata-*.csv`，不修改当前metadata、图片、label或改框备份。压缩前后校验源文件未变化，归档逐文件验证SHA256，全部通过后才删除原散文件。归档目录须为尚不存在的新目录，位于正式数据集之外；归档中包含原文件名、时间和manifest。

2026-10-19这次清理的归档为 `dataset_archives/review-metadata-backups-20261019-cleanup/`。需要查看旧版本时先解压到独立目录：

```bash
mkdir -p /tmp/football-backup-restore
tar --zstd -xf dataset_archives/review-metadata-backups-20261019-cleanup/metadata-backups.tar.zst \
  -C /tmp/football-backup-restore
```

原CSV在解压后的 `metadata-backups/` 内；确认要恢复的版本后再操作正式数据，解压步骤本身不会覆盖当前数据集。
