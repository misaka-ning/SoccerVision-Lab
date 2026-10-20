# 整理与冷归档的路径依赖风险

核对日期：2026-10-19（Asia/Hong_Kong）。本报告仅记录组织/迁移影响，不修复dataset.yaml、配置、导入路径或程序接口。当前另有路径修复工作，下面的引用是只读检查时状态；将来迁移前必须重新核对实际版本。旧文档的历史统计和绝对路径不是可直接执行的当前入口。

## 不能移动的活跃依赖

| 风险ID | 被依赖材料 | 已读取的依赖证据 | 组织风险 | 迁移前置条件与验证 | 本轮动作 |
| --- | --- | --- | --- | --- | --- |
| D01 | `dataset_processing/dataset-audit-20261019/data/{inventory,provenance,similarity-pairs}.json`、temporal_pairs.csv、embedding-model、embeddings/gray NPZ | `datasets/v1/scripts/common.py:14`设AUDIT绝对位置；`prepare.py:5,36-42,53`读取这些结果；`screen_pairs.py:50-51`及`select_candidates.py:29-30`直接读NPZ；`validate_view.py:51`读旧对 | 整体audit搬进archive后，v1复建链缺上游输入；这些特征具有已复用的研究状态，不是一般运行缓存 | 原位保留；如另行批准迁移，先生成新只读恢复映射、在独立临时副本验证源SHA/索引连接，不改冻结证据，不能仅换目录名 | 仅记录 |
| D02 | review-reset的`batches/`、immutable50张groups、inventory/proposals | `script/dataset-reviewer/review_football_batch.sh:47-49,56,68-74`从review_records拼接固定名单；`review_football_groups.py:24-26`读共享选择；`script/dataset_config.py:84-88`要求batches存在 | 移走历史目录可能破坏日常按批/按组浏览；名单顺序和左右目同组关系是审核身份 | 重新读取当前共享配置，核实选中版本对应的review_records；在独立副本只读验证名单解析/顺序/SHA，确保原目录无消费者后再审批 | 原位保留 |
| D03 | batch-review的applied/、批准前metadata/inventory、approved-records、snapshot/locks及final-statistics | `maintenance/approve_reviewed_batch.py:96-115`分别保存批准前metadata、inventory、行级决定及前后hash；`maintenance/apply_precheck.py:63-68,91-100`使用不可变名单并记录before/proposed/锁路径 | 扁平合并before或删除相同label破坏每次批准/预审的事务身份；锁日志文件不是当前活锁 | 索引必须保存每次operation_id、前后metadata SHA、批次清单及顺序、原路径、审批依据；完整解压逐项比较；保留可读最终统计入口 | 不合并/不删 |
| D04 | datasets/v0与v1本体、保留/排除样本 | `datasets/v1/REPRODUCE.md:3,19-35`界定独立副本与冻结分配；`scripts/materialize.py:7-9,19-24`拒绝重复物化并验证source hashes；manifest及analysis/reused_evidence记录旧源路径 | 把v0/v1合并或硬链去重会改变独立版本语义，历史绝对路径不能通过盲目替换解决；reserved不参与正式集也不能删 | v0/v1保持不动；未来只在新数据版本中变更，引用旧manifest/hash，不更改已冻结版本的源数据入口 | 不调整数据内容与位置 |
| D05 | `datasets/v1/analysis/round1`、round2、evidence与archived_contact_history | `datasets/v1/scripts/archive_contact_history.py:6-20`按原页SHA恢复18份历史联系图；`scripts/seal_version.py:14,23-36`将这些文件纳入封存哈希 | 同名轮次文件并非重复垃圾；删图/合并轮次会破坏当时判定和输出哈希索引 | 原位保留；未来独立冷归档需同时保存其轮次、原path、page SHA及观察关联，并给完整恢复索引 | 不重压/不删 |

## 历史事务与恢复依赖

| 风险ID | 证据链 | 依据与风险 | 批准迁移前置条件 / 回滚 |
| --- | --- | --- | --- |
| D06 | audit隔离链：frozen inventory→isolation/plan→journal/result→`datasets/v0/excluded/manifest`→verification→isolation/backup | `dataset-audit-20261019/REPRODUCE.md:5-14,32-34`明确原inventory记录的是隔离前8398项；`scripts/verify_isolation.py:53-88`读取backup路径并比较500份；`isolation/REPORT.md:5-21`记录全量对比 | backup内容与现excluded相同仍需保留恢复身份。本轮500份均与v0唯一现存文件SHA一致；归档必须保留原始来源/目标/backup映射、permissions和新恢复位置。只在目标缺席且SHA相符时恢复，不复跑isolate_excluded |
| D07 | source-resplit before/files与before/proposed文档→plan/journal/result/manifest→verification | `source-resplit-20261019/REPORT.md:55-60`要求保存2370份副本及事务；`scripts/resplit_sources.py:18-23,58-80`既按__file__定位输出也硬编码旧DATA/AUDIT/锁程序路径 | 该历史6925/1223/0划分不同于v1；不能用移动目录来重演迁移。2370份副本与当前v0逐SHA一致，但回滚需要旧split/路径/权限。按整事务归档，恢复树不等于恢复数据分集；真正回退数据需另行批准 |
| D08 | box baseline、两次apply before/proposed/result，与confidence baseline/decisions/before metadata | `box-audit-20261014/审核说明.md:23,40,54-60`和`confidence-review-20261014/审核说明.md:32-51`区分label修正与metadata审批；前后人工冲突跳过是有价值结果 | 不把所有before当一份备份。本轮box基线8398份label有638份与v0现值不同；review-reset首次before1000份有63份不同。不同历史状态完整封存，不能据当前标签替代 |
| D09 | history/processing-code与旧dataset_processing输出树 | `script/dataset-reviewer/history/processing-code/README.md:3-9`已说明134份历史代码迁移但未改内容；原path→新path及SHA在`reports/review-tool-cleanup-20261019/code-migration.json`；例如旧`collect_batch006.py:15-18`使用HERE.parent跨阶段位置 | 旧源码目录旁不再有同一套输入；不执行修复、不额外迁移源码。未来复算只在独立副本恢复输入树并明确重定向读写根；保留代码迁移映射 |
| D10 | 图片证据页→人工/助手观察→候选pair编号/SHA→最终报告 | `dataset-audit-20261019/REPRODUCE.md:40-46`明确重算排序/pair_id会变化，不能仅按编号套用原观察；data/output-files及rendered-pair-evidence记录页身份 | review/thumbs、pair-pages、samples虽可渲染但有观察关联。冷归档可分媒体包，必须保留原成员path、SHA、观察文件和恢复说明；全量恢复验证后才能审批移走 |
| D11 | provenance历史证据缓存→来源判定 | `dataset-audit-20261019/REPRODUCE.md:48-56`说明10份原字节文本，8份历史来源证据、2份规范/基线；sources.json记录旧路径/cache_relative_path/SHA | 保留缓存与原路径映射即可使上游来源文字可查，不需复制视频；不能删除sources.json、只留摘要，也不能从文件名补造未知session |

## 经核验冗余与可再生文件的边界

- safety/verify-copies：64文件全部与v0当前或排除原件唯一匹配且SHA一致；`training-safety.json:57-58`等仍引用物理副本路径。保留两期training-safety、source-excerpts、data/output-files及当前原件映射后才可申请清理；原测试不因副本相同变成64次独立实验。
- `safety/source-excerpts/`是当时实际库行为的实现证据，训练安全报告逐项引用，不能与物理测试副本一起删。
- matplotlib字体缓存、Ultralytics本机settings通常可重建；它们可能已在output-files被索引。用户批准删除后仍应新增解释记录，不改原索引伪造历史一致。
- safety/hash-probe来自`training_safety.py:163`的哈希函数行为测试，18字节。可再生但空间收益近零，随完整阶段归档更省维护成本。
- 旧快照曾列出的不存在preview/cache不列作当前回收空间；UI session、log、smoke、locks没有按名称获得清理资格。

## 与本次结构整理分离的路径事实

已有文档仍保留迁移前 `datasets/` 根和 `dataset_versions/football_holdout_20261019_v1/` 的绝对路径，例如v1/REPRODUCE.md:12,27,39和历史common.py。另有当前共享配置入口已经出现。它们应由用户正在进行的路径修复工作处理；本轮不执行这些命令，不修改dataset.yaml、lists、训练配置、导入接口或冻结报告。

整理的迁移门槛应是“实际消费者已经核对并能通过新恢复索引独立复现”，而非“文档看起来没有旧路径”。正式迁移前重新扫描引用并保留旧/新位置、文件数、bytes、SHA、验证方法和回滚规则；遇到目标冲突停止，不覆盖。

本轮用户明确确认原YOLO26s权重未见当前Test、见过部分Train。旧SOURCE_FACTS、weight_exposure、COMPLETED中unknown是当时判断，保留其历史字节并在新研究索引引用当前确认；不主动改旧模型、旧证据或据此启动评估。

## 执行边界

末次内容复核观察到共享配置工具由并行路径工作移入 `script/common/`，部分入口随之更新。上表的文件/行号是初始盘点证据，不代表本轮修改这些入口；新的实际路径需在未来归档执行前再核对。变化另记，不对旧证据或并行代码做回滚。

本轮可执行：新增用途说明、阶段导航、计划、只读索引和未运行的归档工具；所有旧材料保持原位。任何旧证据搬移、删除、用压缩包替换原树、数据版本合并、训练入口修改、Git历史/远端操作均须用户明确批准。压缩包存在和压缩包校验通过，均不足以单独授权删除源材料。
