# 数据审核、版本选择与日常操作

[返回项目首页](../README.md) · [审核工具](../script/dataset-reviewer/README.md) · [完整操作手册](../script/dataset-reviewer/docs/user-guide.md) · [数据字段](../script/dataset-reviewer/docs/data-format.md)

本页承接原首页的日常审核说明；工具、数据、固定批次和历史证据均留在原位置。科研实验使用冻结v1，新增数据/标注修订应在新的工作版本完成，不覆盖已发布实验的冻结输入。

## 选择数据版本

[script/config.yaml](../script/config.yaml)中的`dataset_version`决定通用审阅、训练、评估和仓库工具的默认版本，当前为v1。保存后重新运行入口即可生效，不需要因切换配置重新编译Qt；已经运行的窗口或训练不会中途切换。显式`--dataset` / `--data`优先，断点恢复保持checkpoint原参数。[共享配置说明](../script/common/README.md)

|版本|用途与注意事项|依据|
|---|---|---|
|v0|原审核资料，Train6925/Val1223/Test0；metadata仍保留排除历史，统计时过滤reviewed_excluded|[版本导航](../datasets/VERSION_INDEX.md)、[v0划分](../datasets/v0/SPLIT_POLICY.md)|
|v1|冻结Train4346/Val1223/Test464；Test为同场次片段留出，buffer/heldout_unused不进入训练|[v1说明](../datasets/v1/README.md)、[分集报告](../datasets/v1/REPORT.md)|

原审核共8398张，8148张可用，250张隔离；此前统计和后续来源重分不是同一个时间点。按日期查看[最终审核统计](../dataset_processing/batch-review-20261016/final-statistics-20261019/REPORT.md)、[来源重分记录](../dataset_processing/source-resplit-20261019/REPORT.md)和[处理阶段索引](../dataset_processing/STAGE_INDEX.md)，不要用旧split计数覆盖新版本。

版本内历史YAML/名单可能有旧绝对路径。共享工具生成本机运行YAML到`experiments/configs/datasets/`，不修改冻结文件；数据存在性、审核状态及hash检查的范围见[仓库工具](../script/repository/README.md)。部分校验/恢复命令会遍历所选版本各集合，不能把它们当作“不接触Test”的阅读检查。

## 启动人工审核

以下从仓库根目录执行，仅在需要审核的工作数据上运行。审核界面会打开图片，保存会修改metadata，手工改框会修改label；它不是冻结实验的只读报告浏览器。

```bash
# 跟随共享配置启动；首次会自动构建
bash script/dataset-reviewer/review_dataset.sh
# 显式选择待审核数据，避免误用其它版本
bash script/dataset-reviewer/review_dataset.sh --dataset /绝对路径/待审核数据集
# 每页50张平铺
bash script/dataset-reviewer/review_dataset.sh --dataset /绝对路径/待审核数据集 --gallery
# 仅构建，不打开数据
bash script/dataset-reviewer/review_dataset.sh --build-only
```

依赖Linux桌面、Bash、CMake≥3.21、Ninja、C++17、Qt≥6.8 SDK；默认`$HOME/Qt/6.8.3/gcc_64`，其它位置通过`QT_PREFIX`指定。共享配置读取需要PyYAML，可用`FOOTBALL_DATASET_PYTHON`选择已有环境。[完整构建说明](../script/dataset-reviewer/README.md#快速开始)

## 框、场景与保存

1. 核对足球框的位置、大小、漏框和误框；双击图片可进入label编辑。
2. 分别确认`Small`、`Occluded`、`Blurred`、`No Ball`。这些是独立图级标记，允许重叠；不是新的检测类别。
3. **A**确认label，**Enter**确认场景并进入下一张；两种审核分别完成。**Ctrl+S**保存修改，左右键浏览。
4. 空label必须确认无球；缺失label不能视为负样本。无法可靠辨认时保留uncertain原因，不直接当No Ball。
5. 平铺按**G**进入/返回；浏览、翻页和看图不等于审批。导出审核数据集到源目录以外的新目录，保留uncertain/excluded的独立身份。

图片只读；metadata/label覆盖前有备份。`reviewed_excluded`表示已经人工审核但不进入训练，不属于待审或无球负样本。具体规则见[标注规范](../script/dataset-reviewer/docs/annotation-policy.md)、[保存与快捷键](../script/dataset-reviewer/docs/user-guide.md)。

YOLO通用训练入口**不会按metadata审核标记自动筛选**；正式训练须使用已核验的集合。实验入口还会核对冻结成员和内容hash，不能通过随意调整metadata或名单绕过。

## 历史批次与只读进度

固定批次属于v0；先选v0才能按其名单复看，v1不沿用这些旧名单，也不重置已完成的审核状态。

```bash
# 第9批的第1组；会打开对应图片
bash script/dataset-reviewer/review_football_batch.sh 9 --group 1
# 只查看固定组通过/待处理数量
bash script/dataset-reviewer/review_football_batch.sh 9 --groups
# 有待审组时才打开，全部完成则给出完成提示
bash script/dataset-reviewer/review_football_batch.sh 9 --group next
```

`review_football_groups.py`查询固定分组与进度，`render_football_review_grid.py`生成只读平铺图；这些脚本均在[审核产品目录](../script/dataset-reviewer/README.md#每次查看50张)。旧`script/review_dataset.sh`已迁至`script/dataset-reviewer/review_dataset.sh`，本地快捷方式使用新路径。

## 新视频与审核链追溯

项目内[football-dataset-curation技能](../.agents/skills/football-dataset-curation/SKILL.md)包含提帧、去重、场景整理和足球预标注脚本。需要补充数据时可按该技能的说明调用：

```text
$football-dataset-curation /绝对路径/录像.avi
```

自动框仍需人工核对。一次性历史审核源码在`script/dataset-reviewer/history/processing-code/`，不是当前常规操作入口；原批准事务和恢复证据继续按[处理阶段](../dataset_processing/STAGE_INDEX.md)查找。不要为了浏览历史而运行旧reset/apply/isolate/resplit脚本。

审核产品的[开发验证](../script/dataset-reviewer/docs/development.md)、[架构](../script/dataset-reviewer/docs/architecture.md)与[变更记录](../script/dataset-reviewer/CHANGELOG.md)仍为维护入口。旧CSV备份归档及本地清理记录保留原位，未随本次文档整理移动或删除；本地路径的可用范围见[复现与产物](REPRODUCIBILITY.md)。
