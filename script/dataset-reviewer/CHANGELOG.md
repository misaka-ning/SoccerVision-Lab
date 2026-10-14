# 变更记录

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
