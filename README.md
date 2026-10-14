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
│   └── dataset-reviewer/                   # 唯一数据集审核产品
│       ├── review_dataset.sh               # 自动构建和启动入口
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

截至 2026-10-14，本次目录整理读取的 metadata 共 **8398 张图片记录**：train 8100、val 170、test 128。实时审核状态以 `datasets/metadata.csv` 为准。

当前检测类别约定为 `0 = football`，`Small`、`Occluded`、`Blurred`、`No Ball` 是独立场景标记。空 label 需人工确认无球；缺失 label 仍需检查或补框。目录和字段定义见 [数据约定](script/dataset-reviewer/docs/data-format.md)。

`datasets/dataset.yaml` 的 `path` 当前指向 `/home/misaka/workspace/datasets`，迁移工作空间后需更新。正式训练前应完成审核或另行整理已确认子集；YOLO 训练不会自动读取 metadata 审核标记来筛选样本。

`baseline/original_best.pt` 为参考权重，`baseline/yolo26s.txt` 为模型名称记录；使用参考权重前需要核对实际类别映射。当前工作空间没有统一训练启动入口。

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
