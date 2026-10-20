# 推荐目标结构与落地边界

目标是增加导航和生命周期规则，保持现有原路径。`[现有]`不移动，`[新增]`是本轮只读说明/模板，`[未来]`须按需创建，涉及旧材料变动时另行批准。

```text
workspace/
├── baseline/                          [现有] 权重、架构、原manifest原样保留
│   ├── original_best.pt               不改名、不改字节
│   ├── original_model.yaml
│   ├── baseline_manifest.json
│   └── README.md                      [新增] 用途/来源与最新曝光确认的引用
├── datasets/                          [现有] 两个独立版本，不合并/去重
│   ├── VERSION_INDEX.md               [新增] 只导航，不替代冻结manifest
│   ├── v0/                            数据本体、metadata、excluded250、恢复点
│   └── v1/                            正式4346/1223/464、reserved2115、证据/脚本
├── dataset_processing/                [现有] 六阶段原树保持；无需新增active/history层
│   ├── STAGE_INDEX.md                 [新增] 生命周期、依赖和阶段入口
│   ├── box-audit-20261014/
│   ├── confidence-review-20261014/
│   ├── review-reset-20261015/          固定批次路径仍可达
│   ├── batch-review-20261016/          候选/应用/用户批准/统计链保留
│   ├── dataset-audit-20261019/         data是v1复建上游
│   └── source-resplit-20261019/
├── dataset_archives/
│   ├── review-metadata-backups-20261019-cleanup/  [现有] 有效包不重压
│   ├── README.md                      [新增] 唯一归档规范与恢复流程
│   ├── ARCHIVE_MANIFEST.schema.json    [新增] 新包元数据结构
│   ├── CATALOG.csv                    [新增] 只注册已有包，不假称新包已建立
│   └── 2026/<stage>/<archive_id>/      [未来] 获准后封存
│       ├── payload.tar.zst
│       ├── manifest.json              包SHA、来源、角色、原因、依赖、恢复规则
│       ├── files.csv                  原path→成员path，bytes/SHA/权限/时间
│       ├── VERIFY.json                全成员+独立恢复结果
│       └── RESTORE.md                 无覆盖恢复步骤与冲突规则
├── script/                            [现有] 不改接口或目录
│   ├── config.yaml                    另行路径修复任务负责
│   ├── common/                        并行工作新归并的共享配置读取器/依赖/测试
│   ├── dataset-reviewer/              活动src/tests/maintenance；history独立
│   ├── model-training/
│   ├── model-evaluation/
│   └── repository/
├── experiments/
│   ├── README.md                      [新增] 唯一run与输出引用约定
│   ├── _template/run_record.json      [新增] 一份管理模板；非训练配置
│   ├── E00_original/                  [现有] 空预留，不填虚构结果
│   ├── E01_baseline/                  [现有] 空旧预留，不重命名
│   ├── train/、eval/、configs/         [现有约定] 工具输出仍使用实际路径
│   └── E01_finetune、E02_c3k2、E03_p2、E04_neck/ [未来] 按需建立设计
│       ├── PLAN.md                    假设、对照、唯一改动和固定条件
│       └── runs/<UTC>_s<seed>_<suffix>/
│           ├── run_record.json        实际结构/初始化/数据/源码/配置指纹
│           ├── config/ + environment/ 小型事实快照，不复制完整数据
│           ├── train/                 独立best/last/logs/results
│           ├── evaluation/val/<eval_id>/
│           ├── evaluation/test/<eval_id>/   仅冻结候选后的正式最终评估
│           └── deployment/<device>/<measurement_id>/
├── benchmarks/
│   ├── README.md                      [新增] 结果纳入标准与比较边界
│   └── runs.csv                       [新增] 空表头，未来引用真实run
├── docs/WORKSPACE_FILE_STRUCTURE.md    [现有] 历史详细快照，不再复制生成
└── reports/workspace-organization/    [新增] 本次唯一方案与核验交付目录
```

新实验目录是推荐管理层，当前工具并未自动集成这一输出树；可先在run中引用既有train/eval的真实路径，不移动既有输出。`config/`只保存本次实际生效的小型配置与哈希，不用它复制数据集。初始化权重引用baseline SHA及来源，不再给每个实验复制一份原始权重。

目标结构里的年份层只用于未来冷归档，不移动现有stage树。归档创建、原件清退分别审批；恢复原树也不是批准重新运行旧重置、隔离或重分脚本。当前 `MOVE_PLAN.csv` 为零项。

末次复核发现共享工具已由并行工作迁入 `script/common/`；这里据实更新导航，不是本轮执行的移动。输入清单保留最初盘点状态，差异另列为并行变更，不回写旧文件或追修接口。
