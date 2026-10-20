# 足球数据集审核工具

用于本地人工审核 YOLO 足球数据集的桌面工具。支持每页50张平铺、图片和检测框预览、四项场景分类、图形化修改 label，以及独立确认场景和标注审核结果。当前应用版本为 **1.4**，使用 C++17 / Qt 6.8。

## 快速开始

支持 Linux 桌面环境。准备 Bash、CMake ≥ 3.21、Ninja、C++17 编译器及 Qt ≥ 6.8 SDK（Core、Gui、Widgets）；运行测试还需要 Qt Test。默认 SDK 为 `$HOME/Qt/6.8.3/gcc_64`。

从克隆后的仓库根目录运行；下方相对路径均以该目录为基准：

```bash
./script/dataset-reviewer/review_dataset.sh
# 明确选择数据集：位置参数和 --dataset 均可
./script/dataset-reviewer/review_dataset.sh --dataset /你的/数据集
# 按名单审核一批图片，仍直接保存到原数据集
./script/dataset-reviewer/review_dataset.sh --dataset datasets/v0 \
  --image-list dataset_processing/review-reset-20261015/batches/batch-001.txt
# Qt SDK 位于其他目录
QT_PREFIX=/你的/Qt/SDK ./script/dataset-reviewer/review_dataset.sh
# 只构建，不打开窗口
./script/dataset-reviewer/review_dataset.sh --build-only
```

启动入口可从任意工作目录调用。第一次启动或源码 / CMake 配置变化后自动构建，程序生成在 `build/release/football-dataset-reviewer`。文档和核验图片的变化不会触发重新构建。

通过 `review_dataset.sh` 启动时，每次从 [../config.yaml](../config.yaml) 读取所选版本，再把数据路径作为 `--dataset` 传给Qt程序；加上 `--gallery` / `--image-list` 等参数时也跟随共享选择。修改YAML后重新运行即可生效，配置变化不会触发C++编译。显式 `--dataset` 或位置参数优先。配置读取依赖PyYAML，本机自动使用已有VisionStudio Python，可通过 `FOOTBALL_DATASET_PYTHON` 覆盖。直接运行编译出的二进制时请显式传入 `--dataset`。

`--image-list` 使用 UTF-8 文本，每行一个 `metadata.csv`「图片」列中的完整文件名，按名单顺序浏览；空行忽略，重复、未知名称及空名单会拒绝启动。窗口显示批次名、本批数量及全库数量。批次仅限制浏览和筛选，保存仍写原始 `metadata.csv` / `labels/`，无需复制数据集。每批审核结束后用另一份名单重新启动即可；名单不代表审核通过。

## 每次查看50张

审阅代码已统一在本目录。普通启动后按G，或直接打开全库平铺：

```bash
./script/dataset-reviewer/review_dataset.sh --gallery
```

历史9批已全部由用户完成复核，固定名单继续保留，属于 **v0**；先将共享配置切换为v0，再按原批次重新查看，不重置审核状态。v1不使用这些旧批次，未建立对应版本名单时会明确报错：

```bash
# 最后第9批398张，共8页，末页48张
./script/dataset-reviewer/review_football_batch.sh 9 --group 1
# 查看各固定组的通过/待处理数量
./script/dataset-reviewer/review_football_batch.sh 9 --groups
# 仅当仍有待审组时才打开；全部完成时打印完成提示
./script/dataset-reviewer/review_football_batch.sh 9 --group next
```

`--group` 加载整批固定组名单，从指定页开始，顶部“前50张/后50张”连续翻页。编号和左右目分组不随审核进度改变。缩略图只列值为1的中文场景名，四项全0留空；点击图片进入单图修改，保存后按G返回。平铺浏览、点击和翻页不自动批准图片，平铺禁用A/Enter/数字分类等隐藏单图快捷键。

固定名单工具为 `review_football_groups.py`，只读状态查询可使用 `status --batch 9`；`render_football_review_grid.py` 可按已有分组生成只读平铺图，依赖本机Pillow环境。临时预览输出仍写到 `dataset_processing/`，源码不再散放到记录目录。

## 日常审核

1. 筛选待 label 审核样本，检查位置、框大小、漏检和误检。
2. 需要修正时，双击图片进入 label 编辑窗口；保存后仍须人工审核通过。
3. 核对 `Small`、`Occluded`、`Blurred`、`No Ball` 四项独立分类。
4. 按 **A** 确认 label，通过后保存；按 **Enter** 确认场景分类并进入下一张。
5. 无法可靠辨认或定位时，选择不确定原因，点击「标记 uncertain 并保存」。看不清不能直接标为无球。
6. 用 **Ctrl+S** 保存分类修改，用左右方向键浏览图片。
7. 点击「导出审核数据集…」，指定源数据集以外的新目录。正式训练、验证和测试使用导出的 `dataset.yaml`。

场景分类与 label 审核分别确认。空 label 需人工确认 `No Ball=1` 才能通过；缺失 label 和非法框不能直接通过。图片只读，保存会更新 `metadata.csv`，手工改框会更新对应 label；覆盖前的备份保存在数据集内。

不确定样本保留原图和原 label，支持独立筛选及重新复核；导出时复制到 `uncertain/`，不进入普通 YOLO 的 train/val/test。导出仅收录场景和 label 均人工通过的样本。源目录仍为审核资料库，直接使用旧训练配置不会自动排除不确定样本。详见 [标注规范](docs/annotation-policy.md)。

人工已完成复核、仍无法可靠用于训练的样本可记录为 `reviewed_excluded`：球框与场景均已审核，界面显示“已审核 · 暂不训练”，原框、分类和具体原因继续保留。导出时单独放到 `excluded/reviewed/`，框保存在 `reference_labels/`；这类样本单独计数，不当作待审核或无球负样本。

## 产品目录

```text
dataset-reviewer/
├── review_dataset.sh            # 日常自动构建/启动
├── review_football_batch.sh     # 按历史固定批次/50张组浏览
├── review_football_groups.py    # 固定名单、进度查询
├── render_football_review_grid.py
├── CMakeLists.txt
├── src/                        # Qt界面、数据层、框编辑、Qt锁程序
├── maintenance/                # 审核批准/候选写入/CSV工具/备份压缩
├── tests/                      # C++数据层与Python分组/安全/备份测试
├── docs/                       # 用户、数据、架构、开发文档
├── history/processing-code/    # 已完成审核的134份原始过程源码
├── artifacts/verification/     # 正式历史证据与可再生最新输出
└── build/release/              # 日常Qt程序和锁程序，可重新构建
```

正式数据集、模型权重和Qt SDK位于产品目录之外。当前工作空间为Git仓库，构建、缓存和备份不纳入提交。2026-10-19已清理临时预览、缓存和旧测试构建，正式历史证据及CSV/JSON/label审核记录仍保留；旧CSV自动备份无损归档并保留最近10份。详见 [维护工具](maintenance/README.md) 和工作空间 `reports/review-tool-cleanup-20261019/` 的清理清单。

## 文档导航

- [操作手册](docs/user-guide.md)：分类、label 编辑、快捷键、保存与备份。
- [数据约定](docs/data-format.md)：接入其他数据集时需要的目录和字段。
- [架构说明](docs/architecture.md)：维护代码时查看职责和状态流转。
- [开发与验证](docs/development.md)：从干净目录构建、运行测试、生成核验证据。
- [变更记录](CHANGELOG.md)：本次合并的目录映射和迁移说明。

目前以源码和启动脚本交付，需本机提供 Qt SDK 和构建环境。项目尚未声明开源许可证；对外分发前由维护者明确授权范围和第三方依赖要求。
