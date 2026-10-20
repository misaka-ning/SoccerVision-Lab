# 审核与审计阶段导航

原阶段树保持，避免破坏历史引用。按完整阶段或完整事务组织未来冷归档；年份只放未来冷存层，不给当前目录再套active/history层。

| 阶段 | 研究含义 | 当前访问与未来冷存 |
| --- | --- | --- |
| [box-audit-20261014](box-audit-20261014/审核说明.md) | 初期框审计、baseline、两次应用和差异 | 完整阶段冷存候选；638个旧label不同于当前值，不能用最终label代替 |
| [confidence-review-20261014](confidence-review-20261014/审核说明.md) | 置信度辅助观察、三组决定与metadata审批 | 完整阶段冷存候选，保留当时授权和规则生效范围 |
| [review-reset-20261015](review-reset-20261015/README.md) | 重置历史、9批不可变名单、50图分组、预审 | batches及proposals仍供v0固定批次使用，原位可达；首次预审应用前快照的63个label不同于当前值 |
| [batch-review-20261016](batch-review-20261016/README.md) | 9批用户批准、锁窗口、政策、最终统计 | 批准链与统计热索引保留；before/proposed/applied属于不同事务角色 |
| [dataset-audit-20261019](dataset-audit-20261019/AUDIT_REPORT.md) | 来源恢复、时序/近重复、特征/灰图、观察、隔离250项 | data是v1复建上游，媒体有实际人工观察关联，不整体清缓存 |
| [source-resplit-20261019](source-resplit-20261019/REPORT.md) | 形成v0来源划分的迁移、映射、恢复副本与独立验证 | 完整事务冷存候选；恢复证据树不等于授权回退数据分集 |

按访问频率区分：日常入口、冻结版本依据和最终统计留活跃索引；低频历史可冷存，但必须保留路径身份、审批语义、名单顺序和恢复链。对新阶段只建立一个stage目录；candidate/applied/approved分别有operation_id，阶段封存后不改旧字节。

完整分类和依赖见[本轮方案](../reports/workspace-organization/PLAN.md)、[阶段分析](../reports/workspace-organization/PROCESSING_ANALYSIS.md)、[依赖风险](../reports/workspace-organization/DEPENDENCY_RISKS.md)。归档规范见[dataset_archives](../dataset_archives/README.md)。本轮不迁移、不删原材料、不运行旧reset/apply/isolate/resplit脚本。
