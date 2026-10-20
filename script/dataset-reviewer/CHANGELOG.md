# 变更记录

## 未发布 · 2026-10-19

- 将 `script/` 顶层的分批启动、固定50张分组、平铺渲染和Python测试统一迁入本产品；修正工作空间定位和相对调用路径。
- 安全批准、候选应用和CSV/label工具收进 `maintenance/`，Qt锁程序纳入同一CMake工程；原134份一次性过程源码完整归入 `history/processing-code/`。
- 审核全部完成后清理可再生预览图、Python缓存、旧测试构建和重复锁程序；正式核验证据、阶段记录、label备份及最终统计保留。
- 2918份旧CSV自动备份先无损压缩并逐文件SHA256验证，清理原散文件；最近10份保留。归档工具默认只读计划，验证失败或源文件变化时不删除备份。

## 未发布 · 2026-10-16

- 支持人工已复核但暂不训练的 `reviewed_excluded`，显示中文状态并保留原判断原因。
- 导出时将这些图片和参考框归入 `excluded/reviewed/` 并单独计数；不影响后续批次保存，不把不确定球误作负样本。
- 新增空框、越界参考框的已审排除、跨样本保存和导出隔离测试。

## 1.4 — 2026-10-15

- 场景显示改为仅列值为1的中文名称，四项全0留空，平铺、表格和提示保持一致。
- 分组启动加载完整固定组名单，新增 `--gallery --gallery-page N` 选择起始页，窗口内可连续前后翻页；编号固定为第N组及组内01–50号。
- 增加完整真实名单分页、点图返回、中文分类和无自动审核的只读冒烟核验。

- 增加 `--gallery` 和 G 切换：每页50张完整画面平铺，叠加现有框、固定名单编号、四项分类和审核状态。
- 点击问题图片直接进入既有单图修改，返回平铺保留选中项并刷新；浏览及未选择项不自动审核通过。
- 平铺时禁用会修改隐藏单图的审核/分类快捷键，保留明确保存与原有数据冲突保护。
- 用临时53图核验50/3分页、固定编号、点击定位、修改刷新和未自动通过。

## 1.3 — 2026-10-15

- 增加 `--image-list` 按图片名单分批审核，显示批次名和数量，保存仍直接更新原数据集完整 metadata 和 labels；拒绝重复或未知图片名单。
- 增加 uncertain 原因选择、独立筛选、保存及重新复核，保留原图和原标签。
- 不确定样本不能标为无球、直接审核通过或强行画框。
- 增加审核快照导出，未确定样本从 train/val/test 排除，独立保存于 uncertain；保留来源、原 split 和版本摘要。
- 明确可见框口径、检测与时序评测边界；增加状态恢复、隔离导出和失败保护测试。

## 未发布 · 2026-10-14

### 项目结构与文档

将原 `script/` 下同一审核工具的源码、启动脚本、测试、操作说明和核验证据统一收进 `script/dataset-reviewer/`。应用仍使用既有版本号 1.2，本次为项目结构整理。

| 原路径（相对 `script/`） | 新路径（相对 `script/dataset-reviewer/`） |
| --- | --- |
| `review_dataset.sh` | `review_dataset.sh` |
| `dataset_reviewer/CMakeLists.txt` | `CMakeLists.txt` |
| `dataset_reviewer/main.cpp`、`dataset_store.cpp`、`dataset_store.h`、`label_editor.h` | `src/` 下同名文件 |
| `dataset_reviewer/dataset_store_tests.cpp` | `tests/dataset_store_tests.cpp` |
| `README_数据集审核.md` | `docs/user-guide.md` |
| `review_dataset_verification/` | `artifacts/verification/history/` |
| `.dataset-review-build/` | `build/release/`（重新生成） |
| `.dataset-review-test-build/` | `build/test/`（重新生成） |

更新 CMake 源码路径、启动脚本的项目定位和默认数据集查找，增加产品 README、数据约定、架构与开发说明、构建忽略规则。工作空间 README 改为指向唯一产品入口。

### 迁移方式

旧启动路径不再保留。将本地快捷方式或调用命令改为 `/home/misaka/workspace/script/dataset-reviewer/review_dataset.sh`。CMake 缓存绑定旧绝对路径，不应直接复用；新目录验证成功后移除旧构建缓存。历史日志中的旧路径和样本数量保留原样，代表核验当时的状态。

此前未维护正式变更日志，因此不追溯编造 1.0 / 1.1 / 1.2 的发布日期或发布说明。
