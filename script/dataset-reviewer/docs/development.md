# 开发与验证

## 环境和构建

在本产品目录执行以下命令。Linux、CMake ≥ 3.21、Ninja、C++17 和 Qt ≥ 6.8 是基线。`QT_PREFIX` 指向 SDK 根目录，不能指向其 `bin/` 或 `lib/`。

```bash
cd /home/misaka/workspace/script/dataset-reviewer
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

`review-store-tests` 使用临时目录，覆盖 CSV 转义 / Unicode / BOM / 附加列保留、只读字段、锁竞争、外部修改冲突、备份失败、YOLO 框合法性、缺失与空 label、审核状态约束以及手工改框的备份和冲突处理。

## 界面冒烟核验

`--smoke` 是已有的开发核验参数。使用测试构建可额外检查快捷键及画框、移动、缩放、删除、取消和保存等交互。无需桌面显示时使用 Qt offscreen 插件：

```bash
LD_LIBRARY_PATH="$QT_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
QT_PLUGIN_PATH="$QT_PREFIX/plugins" \
QT_QPA_PLATFORM_PLUGIN_PATH="$QT_PREFIX/plugins/platforms" \
QT_QPA_PLATFORM=offscreen \
  ./build/test/football-dataset-reviewer \
  --dataset /home/misaka/workspace/datasets \
  --smoke "$PWD/artifacts/verification/latest"
```

程序对指定数据集做只读预览，并复制样本到临时目录测试保存；截图和 `smoke.json` 写到输出目录。输入至少应有一个有效有框样本和一个空 label 样本；真实缺失 label 样本可选，相关路径另由临时样本核验。检查退出码为 0 且报告 `success=true`。offscreen 截图证明程序和自动交互可运行，真实桌面的显示效果仍需桌面复核。

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
