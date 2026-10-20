# 足球检测数据与审核工作空间

本工作空间保存足球 YOLO 数据集、参考模型和本地人工审核工具。**日常使用从 [足球数据集审核工具](script/dataset-reviewer/README.md) 开始，当前数据集位于 `datasets/`。**

## 目录

```text
workspace/
├── README.md
├── .agents/skills/football-dataset-curation/ # 项目内视频整理技能及配套脚本
├── baseline/                               # 参考权重与模型名称记录
├── datasets/                               # 当前数据集
│   ├── metadata.csv                        # 分类、审核状态及来源信息
│   ├── dataset.yaml                        # YOLO 数据配置
│   ├── images/{train,val,test}/
│   └── labels/{train,val,test}/
├── script/
│   ├── model-training/                     # 模型训练脚本、YAML 配置及使用说明
│   └── dataset-reviewer/                   # 唯一数据集审核产品
│       ├── review_dataset.sh               # 自动构建和启动入口
│       ├── review_football_batch.sh         # 固定批次与50张分组入口
│       ├── review_football_groups.py        # 分组及进度查询
│       ├── render_football_review_grid.py   # 只读平铺图
│       ├── maintenance/                    # 安全批准、候选应用、备份压缩
│       ├── history/processing-code/        # 原始审核过程源码归档
│       ├── CMakeLists.txt
│       ├── src/                            # C++17 / Qt 6.8 程序
│       ├── tests/                          # 数据层测试
│       ├── docs/                           # 用户、数据、架构、开发文档
│       ├── artifacts/verification/         # 核验截图与报告
│       └── build/                          # 可重新生成的构建产物
├── benchmarks/                             # 基准结果预留目录
├── experiments/                            # 实验预留目录
└── reports/                                # 报告预留目录
```

审核产品的源码、测试、文档及核验记录均集中在 `script/dataset-reviewer/`。数据与模型位于产品目录之外；数据整理技能中的辅助脚本仍随该技能维护。

## 启动审核

```bash
cd /home/misaka/workspace
./script/dataset-reviewer/review_dataset.sh
# 明确指定数据集
./script/dataset-reviewer/review_dataset.sh --dataset /home/misaka/workspace/datasets
# 仅构建
./script/dataset-reviewer/review_dataset.sh --build-only
```

首次启动自动构建，需本机具备 CMake、Ninja、C++17 编译器和 Qt 6.8 或更新 SDK。Qt 默认位置为 `$HOME/Qt/6.8.3/gcc_64`，其他位置通过 `QT_PREFIX` 指定。详见 [产品 README](script/dataset-reviewer/README.md)。

核对检测框、四项场景分类后，用 **A** 确认 label，用 **Enter** 确认场景并进入下一张，用 **Ctrl+S** 保存。两项审核分别确认。图形修改框、快捷键和备份规则见 [操作手册](script/dataset-reviewer/docs/user-guide.md)。

## 当前数据

截至2026-10-19，8398张图片已全部完成球框和场景审核：8148张可用，250张已隔离至 `datasets/excluded/`，待审0张。按用户指定来源重分后，可用Train为6925张（18:15:31视频及legacy），Val为1223张（10:47:48及18:13:26视频），Test暂空，待独立补采。[当前划分说明](datasets/SPLIT_POLICY.md)及[重分与校验记录](dataset_processing/source-resplit-20261019/REPORT.md)记录当前版本；[此前统计](dataset_processing/batch-review-20261016/final-statistics-20261019/REPORT.md)与[科研审计](dataset_processing/dataset-audit-20261019/AUDIT_REPORT.md)保留为重分前的历史快照。根metadata仍含250条排除历史记录，统计当前集合须先过滤 `reviewed_excluded`。

当前检测类别约定为 `0 = football`，`Small`、`Occluded`、`Blurred`、`No Ball` 是独立场景标记。空 label 需人工确认无球；缺失 label 仍需检查或补框。目录和字段定义见 [数据约定](script/dataset-reviewer/docs/data-format.md)。

`datasets/dataset.yaml` 的 `path` 当前指向 `/home/misaka/workspace/datasets`，迁移工作空间后需更新。正式训练前应完成审核或另行整理已确认子集；YOLO 训练不会自动读取 metadata 审核标记来筛选样本。

`baseline/original_best.pt` 为参考权重，使用前需要核对实际类别映射。统一训练入口与 YAML 配置见 [模型训练说明](script/model-training/README.md)，默认按单类足球数据集微调 YOLO26s，结果保存到 `experiments/train/`。

## 视频整理技能

[football-dataset-curation](.agents/skills/football-dataset-curation/SKILL.md) 是项目内技能，配套脚本和参考规则位于其目录。需要从视频补充数据时，在本项目中调用：

```text
$football-dataset-curation /绝对路径/录像.avi
```

该流程负责提帧、去重、场景分类和自动足球预标注；自动框仍需在审核产品中人工核对。

## 开发与迁移

- [开发与验证](script/dataset-reviewer/docs/development.md)：构建、测试、界面冒烟核验。
- [架构说明](script/dataset-reviewer/docs/architecture.md)：模块职责和安全保存流程。
- [变更记录](script/dataset-reviewer/CHANGELOG.md)：旧路径到新产品目录的映射。

原 `script/review_dataset.sh` 入口已移动到 `script/dataset-reviewer/review_dataset.sh`，本地快捷方式应使用新路径。历史核验材料保留在产品内的 `artifacts/verification/history/`，其中的样本数量和路径代表生成时状态。


2026-10-19补充整理：所有审阅入口、分组/平铺脚本、测试及维护代码已集中在 `script/dataset-reviewer/`，一次性过程源码在其 `history/processing-code/` 内。`script/` 顶层只保留审阅、训练两个功能目录和索引。旧CSV自动备份已无损归档到 `dataset_archives/review-metadata-backups-20261019-cleanup/`，最近10份仍留在原处。清理清单与数据一致性核验见 `reports/review-tool-cleanup-20261019/`。
