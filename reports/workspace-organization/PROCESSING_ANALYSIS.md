# dataset_processing 研究阶段与保留价值分析

核对日期：2026-10-19（Asia/Hong_Kong）。先读取 `docs/WORKSPACE_FILE_STRUCTURE.md` 摘要，再只读检查真实目录、研究报告、审批记录、历史脚本与 v1 生成脚本。本文件仅新增分析；没有执行旧脚本、移动、删除、覆盖、重新审核、训练或路径修复。

## 结论

当前无需重新设计全部目录。现有“阶段名 + 开始日期”已经有效区分六个阶段；主要缺口是最新状态导航、跨阶段依赖和统一归档索引。建议先保留所有原路径，通过文档呈现“活跃引用 / 已完成历史 / 可核验冗余 / 可再生本机产物”，待批准再采用 `dataset_archives/2026/<stage>/<archive_id>/` 冷归档。年份放在冷归档层，原阶段目录名和内部相对路径保持不变，避免现在再增加一层文件移动。

本次按真实内容和使用关系分类，不把文件名中的 before、proposed、backup、smoke、log 当作删除依据。统计是普通文件逻辑大小，包含空 label；不等于磁盘实际占用或可释放空间。

## 六个阶段的真实职责

| 目录 | 文件数 | 逻辑字节 | 研究阶段与代表材料 | 当前保留策略 |
| --- | ---: | ---: | --- | --- |
| `box-audit-20261014/` | 9,012 | 68,109,425 | 全量8,398图/5,218原框的助手视觉复核，实际应用267图label调整；baseline、changes.csv、coverage、proposals、两次apply-audits、final-validation | 已完成历史，可整阶段冷归档；baseline及修改前label是核心历史证据，不能删 |
| `confidence-review-20261014/` | 60 | 96,827,910 | 当时4,609待审核图的授权助手复核；球框/分类分别通过，metadata变更，保留remaining-review、all-reviewed、三组视觉观察和before metadata | 已完成历史，可整阶段冷归档；与后续重置不等价，保留原审批语义 |
| `review-reset-20261015/` | 1,962 | 151,132,463 | 全量撤销通过状态并建立9批不可变名单；各组预审、priorities、固定50张组；第9批staged与独立handoff验证 | 固定名单和批次索引仍可能被当前工具访问；暂原位保留，其他历史只能在依赖确认后按整阶段归档 |
| `batch-review-20261016/` | 7,691 | 223,693,817 | 9批用户最终批准，应用前快照、审核窗口/锁记录、approved-records、最终两套独立统计；不是另一份训练集 | 最终统计、政策、9批批准与哈希链属于活跃可查证据；历史应用快照可在整体依赖封存后归档 |
| `dataset-audit-20261019/` | 8,933 | 476,762,604 | 冻结的隔离前科研审计：inventory/来源恢复、图像/像素/label SHA、MobileNet特征、灰图、相似候选、观察记录、250排除样本隔离事务及核验 | 当前 v1 脚本仍依赖 data，原位保留；不能将NPZ或证据页批量称作缓存清理 |
| `source-resplit-20261019/` | 2,390 | 263,499,516 | 曾按录像来源形成6925/1223/0划分的事务，1,185对/2,370文件移动依据、before/proposed/plan/journal/verification | 已完成历史，可在映射清楚后整阶段冷归档；不是当前 v1 的4346/1223/464统计 |
| 根 `README.md` | 1 | 1,060 | 早前代码迁移及材料导航 | 保留，新增导航引用它，不覆盖其历史说明 |
| **合计** | **30,049** | **1,280,026,795** | 约1.192 GiB | 本轮全部保持原位 |

依据：`box-audit-20261014/审核说明.md:6-8,12-23,54-60`；`confidence-review-20261014/审核说明.md:3-19,32-51`；`review-reset-20261015/README.md:3-9,51-62`；`batch-review-20261016/README.md:5-26`；`dataset-audit-20261019/REPRODUCE.md:3-15,21-34`；`source-resplit-20261019/REPORT.md:15-37,47-60`。报告中的旧绝对路径及当时统计属于历史证据，不主动改写。

## 五种保留类别

### A. 活跃可查的核心证据

- v1 当前数据的 manifest、statistics、COMPLETED、verification、SOURCE_FACTS、评估口径及 analysis 中的最终分配、buffer/heldout边界、人工观察、两轮修改理由和输出哈希索引。v1 的 analysis/round1、round2 是有效版本历史，不能按同名文件判断重复。
- `batch-review-20261016/final-statistics-20261019/`：11文件、19,018,196字节，涵盖metadata原件、逐图inventory、主/独立统计、独立逐行结果、250排除名单及核验；其中70项独立检查PASS仅说明当时数据状态，不是未来可变数据的永久合格证。
- 9个 `batch-*-approved/` 成套批准证据：`before/metadata.csv`、`before/inventory.json`、`approved-records.json`、result/verification/REPORT成套保存。9份审批前metadata SHA均不同，不能用最后一份替代所有中间状态。
- `REVIEW_POLICY.md`/`review-policy.json`、固定批次/50张组清单、user-reviewed-snapshot与锁/窗口记录。2026-10-16第5批起遮挡/No Ball口径与10-14不同；它们解释历史阶段差异，不能合并成一份失去生效范围的规则。
- `dataset-audit-20261019/data/`：44文件、203,034,682字节。inventory、provenance、similarity-pairs、temporal_pairs、embeddings、gray NPZ、embedding-model、source metadata/yaml、原始哈希表与来源文本缓存仍构成 v1 复建的上游输入。目录原位保留。
- `dataset-audit-20261019` 的 audit_manifest、REPRODUCE、output-files、观察记录、isolation plan/result/journal/verification，以及 `datasets/v0/excluded/manifest.json`，共同记录250排除样本的身份与去向。

上述“活跃”指科研查证/复建时仍需访问，不代表允许重跑写入脚本。完整路径依赖见 [DEPENDENCY_RISKS.md](DEPENDENCY_RISKS.md)。

### B. 适合冷归档的完整历史材料

- 已完成 box-audit 与 confidence-review 两个完整阶段，可分别归档；保留两者独立ID，不把它们的baseline和before扁平合并。
- review-reset 的重置前snapshot、预审分组和第9批staged，batch-review的各次 applied：候选、执行和最终批准具有不同语义；可在同一封存批次下分包保存，但索引必须互相引用。
- source-resplit 完整事务，包括2,370份移动前文件、三个before文档、三个proposed文档、plan/result/journal/manifest和验证。仅保留最后结果会失去旧路径、当时权限和恢复链。
- audit中的 `review/` 8,228文件、143,327,591字节与 `samples/` 32文件、12,703,541字节可作为证据媒体冷存；它们虽能渲染，但现有观察引用页版本/编号/SHA，不等于无研究价值。若单独分包，必须保留原目录映射并能按manifest恢复。

优先归档粒度是“一次完整阶段或事务 + 原始树”，不是只压缩before，也不是按文件后缀分散。年度目录为冷存导航；具体操作ID仍保留既有日期/随机后缀。优先单包的 box/confidence/source-resplit 合计 **428,436,851 B（约408.59 MiB）**，这是候选源逻辑大小；归档且保留原件时空间增加，批准替换原件后是否回收取决于压缩率、分配块、归档保留位置和Git跟踪情况。

### C. 已有等价现存内容、但身份和恢复关系仍须保留的材料

本轮做了只读逐文件SHA核对，匹配键先取唯一文件名，再比较完整原始字节；没有合并或删除任何文件。

| 材料 | 文件数 | 逻辑字节 | 本轮现存内容核验 | 处理前置条件 |
| --- | ---: | ---: | --- | --- |
| `source-resplit-20261019/before/files/` | 2,370 | 212,756,961 | 全部唯一对应v0的image/label且SHA一致 | 先保留迁移plan/journal/manifest、原split、路径和权限；验证可恢复的完整阶段归档；明确批准后才考虑替换散文件 |
| `dataset-audit-20261019/isolation/backup/` | 500 | 60,310,627 | 全部唯一对应v0/excluded现存image/label且SHA一致 | isolation恢复链仍使用backup路径；需归档内映射及独立恢复验证，不能因当前excluded存在便删 |
| `dataset-audit-20261019/safety/verify-copies/` | 64 | 6,630,770 | 64份全部唯一对应v0当前/排除原件且SHA一致 | 保留training-safety、pre-isolation-training-safety、source-excerpts及output-files索引；记录新路径映射并确认不需复查物理测试副本后再审批 |

C类是“内容等价已核对”，不是“科研身份等价”或“已授权清理”。before文件是当时事务原路径恢复依据，而v0中的文件承担当前数据身份。二者不能只依赖同名和哈希就自动去重。

### D. 可再生且可在核验后申请清理的产物

- 绘图库字体缓存 `dataset-audit-20261019/logs/matplotlib-config/fontlist-v390.json`；本机字体路径/版本会变化，可再生，旧缓存内容不是标注或批准决定。先确认无运行进程占用；删除仍需用户批准。
- Ultralytics本机 `settings.json`：先核对是否含自定义配置，以及生成位置是否被审核manifest列入。它通常可重建，但不能误把相邻的train-dry-run或训练安全报告一并删。
- `dataset-audit-20261019/safety/hash-probe.txt`：18字节，`scripts/training_safety.py:163`中的库哈希行为探针；实验结果记录保留后可再生，回收空间无意义，宜等归档时整体收纳而非单独安排删除。

已清理的旧preview、ROI和Python缓存见原 `reports/review-tool-cleanup-20261019/removed-generated-files.json`，不重复列作本次可回收文件。现存日志、smoke结果、图表及UI session文件没有仅凭名字获清理资格。

### E. 用途或完整等价性不足时保守保留

- 旧UI session / review-window、截图地图中已无原预览的条目、与当前入口不再一一匹配的绝对路径：保留原内容，借助之前迁移报告解释，不改成“丢失垃圾”。
- 未纳入恢复验证的所有新/未知文件，先登记为保守保留；文件名不构成删除依据。
- 过去记录中的权重训练曝光 `unknown` 为历史口径。本轮以用户确认“原始YOLO26s未见当前Test、见过部分Train”为当前权威事实，原权重原路径与字节完整保留；本分析不改写旧记录，也不把旧不确定性覆盖到当前结论。

## 为什么历史label不能机械去重

本轮针对历史label与v0全部当前/排除label做只读SHA比较：

- box-audit baseline的8,398份label：7,760份与现值相同，**638份不同**。
- review-reset首次applied的1,000份before label：937份相同，**63份不同**。
- source-resplit的1,185份label和isolation的250份label全部与现值相同，但仍承担“迁移前身份/回滚位置”角色。

这些对比仅证明字节状态关系，不评判旧新标注优劣。不得将不同阶段label套回当前数据，也不允许把空label当作无研究价值文件。

## 分阶段归档的前置条件、风险和回滚

| 归档单元 | 风险 | 依赖/前置条件 | 合格验证 | 回滚 |
| --- | --- | --- | --- | --- |
| box-audit完整阶段 | 中 | baseline、两次应用记录、差异与原报告完整；历史源码映射一并可查 | 精确成员清单、逐文件SHA、解压到独立空目录全量比对 | 仅在目标缺席时按原路径恢复；冲突停止，保留原件 |
| confidence-review完整阶段 | 中 | 保留三组决定、当时授权语义、before metadata、最终变更/保留名单 | 同上，确认metadata前后哈希链 | 同上，不覆盖后续人工metadata |
| review-reset完整阶段 | 高 | 当前批次入口及配置不再需要原目录；旧代码跨阶段导入与固定组顺序已登记 | 保留batch/group全量名单和顺序哈希，隔离目录检查路径解析 | 先恢复原树再恢复只读引用；不运行reset脚本 |
| batch-review完整阶段或applied子包 | 高 | 批准证据索引、policy、生效范围、锁记录及最终统计保持可达；需要完整跨包ID | 9批前后metadata链、approved-records行级覆盖及所有label SHA | 原树无冲突恢复；不用旧before覆盖现dataset |
| audit媒体子包或整个audit | 高 | v1上游引用已能离线恢复；主manifest和source identity不变；不重编号pair | 全量提取SHA并验证页ID、观察与图SHA联系；外部引用单列 | 恢复原相对路径与目录名，仍按历史基线解释 |
| source-resplit完整阶段 | 中 | 旧split/新split/路径/权限、2370份before与plan/journal完整 | 全量成员+SHA；在临时目录验证backup→预期旧路径映射，不实际移动数据 | 只恢复证据树；若真要回退数据分集须另行批准与锁定核验 |

归档命名示例：`dataset_archives/2026/box-audit/box-audit-20261014-sealed-<creation_utc>/`。每个目录包含唯一压缩包、manifest、files索引、VERIFY结果、RESTORE说明；引用现有包时登记原archive_id/路径/校验值，不能重复压缩现有有效归档。命名与完整规范见主计划。所有归档执行、旧证据移动和原件删除仍待批准。

## 保持整洁的维护规则

1. 一个研究阶段一个目录，一个事务一个operation_id，candidate/applied/approved不混写；阶段结束后冻结，只追加新的索引或新的版本，不覆盖旧证据。
2. 活跃导航引用既有权威文件，不另复制整套metadata、图片、labels、统计和报告；临时可再生产物未来统一落入独立runtime或run目录。
3. 新审核工作建立新日期阶段；当前v0/v1和各自正式、保留、排除样本保持独立。E01/E02只引用冻结版本ID和校验值。
4. 每次归档先生成可复核成员清单与source/destination映射；失败即保留源，不能用归档存在替代恢复验证。
5. 不对旧manifest里的路径做全局文本替换。可移植恢复映射是新索引，旧证据的内容与哈希不变。
