# 开发与验证

## 环境和构建

在本产品目录执行以下命令。Linux、CMake ≥ 3.21、Ninja、C++17 和 Qt ≥ 6.8 是基线。`QT_PREFIX` 指向 SDK 根目录，不能指向其 `bin/` 或 `lib/`。

从仓库根目录进入产品目录：

```bash
cd script/dataset-reviewer
./review_dataset.sh --build-only
```

启动入口固定使用 Release 和 `BUILD_TESTING=OFF`。也可手工构建；以下 `QT_PREFIX` 同时用于 CMake 和运行时库定位：

```bash
export QT_PREFIX="${QT_PREFIX:-$HOME/Qt/6.8.3/gcc_64}"
cmake -S . -B build/release -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="$QT_PREFIX" -DBUILD_TESTING=OFF
cmake --build build/release --parallel 4
```

日常启动仍通过 `./review_dataset.sh`，由入口设置 Qt 运行时库和插件路径。切换 SDK 时建议清理对应构建目录后重建。

## 自动化测试

使用独立 `build/test/`，避免将测试配置混入日常构建：

```bash
export QT_PREFIX="${QT_PREFIX:-$HOME/Qt/6.8.3/gcc_64}"
cmake -S . -B build/test -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="$QT_PREFIX" -DBUILD_TESTING=ON
cmake --build build/test --parallel 4
LD_LIBRARY_PATH="$QT_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  ctest --test-dir build/test --output-on-failure
```

`review-store-tests` 使用临时目录，覆盖 CSV 转义 / Unicode / BOM / 附加列保留、只读字段、锁竞争、外部修改冲突、备份失败、YOLO 框合法性、缺失与空 label、审核状态约束以及手工改框的备份和冲突处理。还覆盖不确定状态恢复、无球互斥、三种 split 导出隔离、非法输入、目标冲突、未保存/过期数据、失败清理和原文件保留。

批次名单测试覆盖 BOM / Unicode / CRLF、名单顺序、未知和重复项、空名单、非法 UTF-8，以及保存时保留完整 metadata 和批外行。界面冒烟还检查批内导航、叠加筛选、批次计数和保存目标；证据为 `batch-filter.png`。也可在 `--smoke` 前追加 `--image-list /名单.txt`，报告中的 `scope_count` 表示本批数量，`row_count` 仍为完整数据集数量；所选批次须含核验要求的有框和空 label 样本。

平铺冒烟使用临时53图验证首页50张/末页3张、固定组号及组内编号、筛选不重编号、全0分类留空及单/多项中文显示；另用批次临时副本验证点击定位、不自动通过、保存分类后返回刷新、平铺禁用隐藏单图审核快捷键。真实名单超过50张时还只读验证首页可前进、第2页组内编号重从01开始、末页余数及可返回、点图再返回保持页与选中项、全库审核状态未变和非法页码拒绝。截图为 `gallery-50.png` / `gallery-batch.png` / `gallery-real-page-02.png` / `gallery-real-last-page.png`，结果在 `smoke.json` 的 `gallery_*` / `real_gallery_*` 项。

## 界面冒烟核验

`--smoke` 是已有的开发核验参数。使用测试构建可额外检查快捷键及画框、移动、缩放、删除、取消和保存等交互。无需桌面显示时使用 Qt offscreen 插件：

```bash
LD_LIBRARY_PATH="$QT_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
QT_PLUGIN_PATH="$QT_PREFIX/plugins" \
QT_QPA_PLATFORM_PLUGIN_PATH="$QT_PREFIX/plugins/platforms" \
QT_QPA_PLATFORM=offscreen \
  ./build/test/football-dataset-reviewer \
  --dataset ../../datasets \
  --smoke "$PWD/artifacts/verification/latest"
```

程序对指定数据集做只读预览，并复制样本到临时目录测试保存；截图和 `smoke.json` 写到输出目录。输入至少应有一个有效有框样本和一个空 label 样本；真实缺失 label 样本可选，相关路径另由临时样本核验。检查退出码为 0 且报告 `success=true`。offscreen 截图证明程序和自动交互可运行，真实桌面的显示效果仍需桌面复核。新流程还核验 uncertain 控件禁用、筛选、重新加载、恢复待审核及导出排除。

需要证明真实数据未改动时，在核验前后比较 `metadata.csv`、`dataset.yaml` 和全部 label 文件的 SHA256。核验输出目录应位于产品 `artifacts/verification/` 内，不放到数据集目录。

## 维护约定

- CMake 配置放在项目根，业务代码放 `src/`，自动化测试放 `tests/`。
- 产品用途和启动要求更新到 README，操作变化更新到用户手册，数据规则更新到数据约定，目录或行为变化记入 CHANGELOG。
- 应用当前版本由 `src/main.cpp` 声明；正式改版时同步 CMake `project(VERSION ...)` 与 README。
- 不提交 `build/` 或 `latest/` 核验产物；保留现有历史证据，追加正式证据时使用明确日期的目录并解释来源。
- 保存逻辑的变更需覆盖相关冲突 / 失败路径；主窗口或编辑窗口的行为变化运行测试构建的界面冒烟核验。
- 分发源码保留 `README.md`、CMake、启动入口、`src/`、`tests/` 和 `docs/`；重新构建产物，不复制绑定本机路径的 CMake 缓存。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 提示未找到完整 Qt SDK | 将 `QT_PREFIX` 指向包含 `lib/cmake/Qt6/Qt6Config.cmake` 和 `plugins/platforms/` 的 SDK |
| 找不到 CMake / Ninja 或编译器 | 准备对应构建工具，再运行 `--build-only` |
| Qt 平台插件加载失败 | 通过启动脚本运行；无桌面核验使用 `QT_QPA_PLATFORM=offscreen` |
| CMake 报源码目录不一致 | 删除该构建缓存目录后，按新产品路径重新配置 |
| 无参数打开的不是目标数据集 | 使用 `--dataset /绝对路径` 明确选择 |
| CSV 或 label 提示外部修改冲突 | 保留当前改动记录，重新加载实际文件、核对后再次修改；详见用户手册 |


## Python与维护代码（2026-10-19整理）

分组、平铺和批次入口位于产品根，Python与C++测试均在 `tests/`，安全维护代码在 `maintenance/`；原 `dataset_processing/` 中一次性源码已归到 `history/processing-code/`，仅作历史参考。以下命令从工作空间根目录执行：

```bash
python3 -B -m unittest discover -s script/dataset-reviewer/tests -p 'test_*.py' -v
./script/dataset-reviewer/review_dataset.sh --build-only
LD_LIBRARY_PATH="$HOME/Qt/6.8.3/gcc_64/lib" python3 -B script/dataset-reviewer/tests/check_approval_safety.py
LD_LIBRARY_PATH="$HOME/Qt/6.8.3/gcc_64/lib" python3 -B script/dataset-reviewer/tests/check_precheck_safety.py
```

以上维护安全测试只写临时夹具，覆盖字段/SHA冲突、Qt锁竞争及双待审语义；备份测试覆盖校验失败不删除、源备份变化不删除、恢复最近备份与归档完整性。生产Qt锁程序与GUI在同一CMake工程构建。旧 `build/test`、`build/uncertain-test` 可在核验后清理，日常 `build/release` 保留以免重新编译。
