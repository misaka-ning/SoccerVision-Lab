# 足球数据集审核工具

用于本地人工审核 YOLO 足球数据集的桌面工具。支持图片和检测框预览、四项场景分类、图形化修改 label，以及独立确认场景和标注审核结果。当前应用版本为 **1.2**，使用 C++17 / Qt 6.8。

## 快速开始

支持 Linux 桌面环境。准备 Bash、CMake ≥ 3.21、Ninja、C++17 编译器及 Qt ≥ 6.8 SDK（Core、Gui、Widgets）；运行测试还需要 Qt Test。默认 SDK 为 `$HOME/Qt/6.8.3/gcc_64`。

从工作空间根目录运行：

```bash
cd /home/misaka/workspace
./script/dataset-reviewer/review_dataset.sh
# 明确选择数据集：位置参数和 --dataset 均可
./script/dataset-reviewer/review_dataset.sh --dataset /你的/数据集
# Qt SDK 位于其他目录
QT_PREFIX=/你的/Qt/SDK ./script/dataset-reviewer/review_dataset.sh
# 只构建，不打开窗口
./script/dataset-reviewer/review_dataset.sh --build-only
```

启动入口可从任意工作目录调用。第一次启动或源码 / CMake 配置变化后自动构建，程序生成在 `build/release/football-dataset-reviewer`。文档和核验图片的变化不会触发重新构建。

无参数时，以项目所在工作空间为基准，依次查找 `datasets/`、`datasets/football_dataset/`、`dataset/football_dataset/`，要求包含 `metadata.csv` 和 `images/`。当前工作空间数据位于 `/home/misaka/workspace/datasets`。将本项目单独复制到其他位置时，建议显式指定 `--dataset`；未找到默认数据集时可在界面中选择。

## 日常审核

1. 筛选待 label 审核样本，检查位置、框大小、漏检和误检。
2. 需要修正时，双击图片进入 label 编辑窗口；保存后仍须人工审核通过。
3. 核对 `Small`、`Occluded`、`Blurred`、`No Ball` 四项独立分类。
4. 按 **A** 确认 label，通过后保存；按 **Enter** 确认场景分类并进入下一张。
5. 用 **Ctrl+S** 保存分类修改，用左右方向键浏览图片。

场景分类与 label 审核分别确认。空 label 需人工确认 `No Ball=1` 才能通过；缺失 label 和非法框不能直接通过。图片只读，保存会更新 `metadata.csv`，手工改框会更新对应 label；覆盖前的备份保存在数据集内。

## 产品目录

```text
dataset-reviewer/
├── README.md                    # 产品入口、环境要求和启动方式
├── CHANGELOG.md                 # 变更与迁移记录
├── CMakeLists.txt               # 唯一 CMake 项目入口
├── .gitignore                   # 构建缓存和新核验产物忽略规则
├── review_dataset.sh            # 唯一日常启动入口
├── src/
│   ├── main.cpp                 # 主窗口、命令行与界面冒烟核验
│   ├── dataset_store.cpp        # CSV、label、审核状态和安全保存
│   ├── dataset_store.h          # 数据层接口
│   └── label_editor.h           # 图形化框编辑窗口
├── tests/
│   └── dataset_store_tests.cpp  # 数据层自动化测试
├── docs/
│   ├── user-guide.md            # 操作、快捷键、备份和冲突处理
│   ├── data-format.md           # 数据目录、字段、审核状态及写入边界
│   ├── architecture.md          # 模块职责与保存流程
│   └── development.md           # 构建、测试、核验和维护约定
├── artifacts/
│   └── verification/
│       ├── README.md            # 证据说明
│       ├── history/             # 迁移前的截图、报告和日志
│       └── latest/              # 新核验输出，自动生成且不纳入版本管理
└── build/
    ├── release/                 # 启动入口生成，可删除后重建
    └── test/                    # 测试构建，可删除后重建
```

数据集、模型权重和 Qt SDK 放在项目之外。`build/` 是可再生成的缓存，`artifacts/verification/history/` 是保留的历史证据，两者用途不同。尚未建立独立 Git 仓库；`.gitignore` 供后续版本管理使用。

## 文档导航

- [操作手册](docs/user-guide.md)：分类、label 编辑、快捷键、保存与备份。
- [数据约定](docs/data-format.md)：接入其他数据集时需要的目录和字段。
- [架构说明](docs/architecture.md)：维护代码时查看职责和状态流转。
- [开发与验证](docs/development.md)：从干净目录构建、运行测试、生成核验证据。
- [变更记录](CHANGELOG.md)：本次合并的目录映射和迁移说明。

目前以源码和启动脚本交付，需本机提供 Qt SDK 和构建环境。项目尚未声明开源许可证；对外分发前由维护者明确授权范围和第三方依赖要求。
