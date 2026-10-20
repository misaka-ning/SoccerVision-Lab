# 已有历史归档核验

核验日期：2026-10-19（Asia/Hong_Kong）。范围仅为现存归档、清单、恢复工具及其依赖；没有移动、删除、覆盖已有文件，没有重新压缩归档，没有改写正式数据。

## 结论

现有 `dataset_archives/review-metadata-backups-20261019-cleanup/` 是有效的旧 metadata 恢复档案，应原样保留。它已替代过去的 2,918 份散文件；本轮不能再次把其 12.72 GiB 原始内容算作可释放空间。**不需要重复压缩，也不建议更名或迁移这个既有归档目录。**

| 项目 | 本轮独立核验结果 |
| --- | --- |
| 压缩包 | `metadata-backups.tar.zst`，71,998,479 B（68.66 MiB） |
| 包 SHA256 | `bd6e5923963bf2439ba7517dc016ecde420f96466a61b50550ad05a483ee9e71` |
| 历史 SHA 比对 | 与 `reports/review-tool-cleanup-20261019/verification.json` 完全一致 |
| 数据文件 | 2,918 份 CSV；13,656,380,391 B；逐成员流式读取并核对大小和 SHA256 全部通过 |
| tar 清单 | 2,919 个普通文件成员＝2,918 CSV＋内部 `manifest.json`；无缺失、额外或重名成员 |
| 内外清单 | 包内 manifest 与同目录外置 manifest 的 JSON 内容一致 |
| 安全路径 | 无绝对成员路径、`..`、软链接或硬链接成员 |
| 磁盘恢复演练 | 按首两份、四分位、中位、四分之三和末份选取 6 份，恢复到新建独立 `/tmp` 目录；重读磁盘后 SHA256 全通过，共 28,343,316 B |
| 原件稳定性 | 核验前后包的大小、mtime_ns、inode 不变；没有写入归档原件 |

全量解压流已经验证，**没有将 13.66 GB 全量落盘恢复**；6 份磁盘样本演练不能表述为全量磁盘恢复。完整核验参数、外置清单哈希、样本名、临时位置与结果见同目录 `EXISTING_ARCHIVE_CHECK.json`。临时恢复目录只是本轮验证产物，不是新的长期备份，不能作为恢复依据；权威归档仍在 `dataset_archives/`。

2,918 个版本名只对应 2,885 种内容 SHA，说明部分时间点内容相同，但它们有独立时间身份；本轮没有去重。当前 `datasets/v0/.metadata-review-backups/` 有 10 份散文件（91,926,916 B），与旧档案的文件名、内容 SHA 均无重合。它们属于后续恢复点，应继续保留；不能说“已有归档覆盖最近 10 份”。

## 路径映射与恢复

| 路径身份 | 规则 |
| --- | --- |
| 归档时来源（历史逻辑路径） | `datasets/.metadata-review-backups/{name}` |
| 归档内部路径 | `metadata-backups/{name}` |
| 当前对应的备份目录 | `datasets/v0/.metadata-review-backups/{name}` |
| 安全恢复输出 | `<新建独立恢复目录>/metadata-backups/{name}` |

来源映射依据是 `compact_metadata_backups.py` 的备份目录契约、维护 README、原清理报告和工作空间迁移快照。**现有 manifest 只保存 basename、size、mtime_ns、inode、sha256，没有显式 source_paths；映射是基于这些证据重建，不能假称包内已经记录完整原路径。** inode 是当时校验信息，异地恢复不要求 inode 相同。

独立查看全部旧版本的命令（仅供将来人工执行，本轮只恢复上述 6 份样本）：

```bash
RESTORE_DIR=$(mktemp -d /tmp/soccervision-metadata-restore-XXXXXXXX)
zstd -q -d -c --long=25 dataset_archives/review-metadata-backups-20261019-cleanup/metadata-backups.tar.zst \
  | tar -x -C "$RESTORE_DIR"
```

执行前确认压缩包 SHA 与上表一致；执行后按外置 manifest 核对成员总数、相对路径、大小和 SHA256。先选择要查看的版本，再决定是否需要恢复正式数据。**解压到独立目录不等于授权写回 `metadata.csv` 或正式备份目录；写回需另行确认目标版本及路径。**

现有 `script/dataset-reviewer/maintenance/compact_metadata_backups.py` 已包含流式校验函数，但 `compact(..., apply=True)` 会删除旧散文件，不能作为本轮的只读核验入口。已有维护 README 的示例 `--dataset datasets` 是迁移前路径；本轮仅记录影响，不修改工具、配置或入口。

## 长期统一规范的兼容方式

保留现有包、manifest 和 result 原字节。用新索引或旁挂 descriptor 补齐统一字段，不改写历史清单；新建归档采用 `dataset_archives/<YYYY>/<审核阶段>/<archive_id>/`，旧档案通过索引接入，避免为了统一外观迁移有效档案。每个 archive_id 表示不可变快照，禁止复用或覆盖。

建议 descriptor 至少包含以下字段：

| 字段 | 本档案可填写的内容或要求 |
| --- | --- |
| `schema_version` | 新索引协议版本；与旧 manifest 格式分离 |
| `archive_id` | `review-metadata-backups-20261019-cleanup`（继承既有身份） |
| `source_paths` | 原路径规则及当前逻辑路径；注明映射证据与重建性质 |
| `creation_time` | `2026-10-19T03:43:12.549986+00:00`，来自 result；另存验证时间，不混淆 |
| `file_count` | 2,918 个数据文件；单独记录 tar 成员数 2,919 |
| `total_bytes` | 原数据 13,656,380,391 B；另存 `archive_bytes=71998479`，不混用 |
| `sha256` | 压缩包哈希；另列外置 manifest、result 和每成员哈希索引 |
| `reason` | 保存旧 GUI metadata 自动恢复点，保留最新散文件；不等于覆盖 label 快照 |
| `restore_instructions` | 工具版本/依赖、独立恢复目录、路径映射、成员校验、禁止自动写回 |
| `verification` | 全成员流式 SHA＋6 份落盘恢复；记录时点和真实覆盖范围 |
| `dependencies` | 维护工具、历史报告、源路径映射和需要连同保存的索引 |
| `rollback` | 新档案尚保留原件时可撤销新增；替代原件前必须批准并完成恢复演练 |
| `publication_status` | `private_pending_rights_review`；未确认图像/权重等授权前不得公开 |

归档应有独立存储副本，并把包、manifest、descriptor、恢复说明作为同一资产集核验。仅有同一工作盘上的压缩包不等于长期备份；新建外部副本属于后续存储安排，本轮未上传或复制到外部服务。

## 必须一起保留的证据

- 三件既有归档资产：压缩包、`manifest.json`、`result.json`。
- `reports/review-tool-cleanup-20261019/README.md`、`verification.json`：压缩时操作范围、历史包 SHA、保护校验。
- `final-metadata-before-cleanup.csv`：清理前真实 metadata 内容；不可用 hash 清单替代。
- `dataset-before.json`、`processing-records-before.json`：历史路径与哈希索引；它们不是数据内容的恢复副本。
- `code-migration.json`、`script/dataset-reviewer/history/processing-code/` 与维护源码：恢复解释和旧路径追溯依赖。
- `datasets/v0/.label-review-backups/` 及历史 before/proposed/applied label：本 CSV 归档没有覆盖它们，必须独立保留。

以上应视作一个研究证据依赖组。对包内等 SHA 的不同时间版本、本地 label 快照、最近 metadata 备份，均不提出无条件删除建议。
