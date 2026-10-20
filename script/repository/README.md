# 仓库数据准备与校验

两个入口使用 Python 3.10+ 和PyYAML，从脚本自身位置定位仓库，支持从任意工作目录运行。每次读取 [../config.yaml](../config.yaml) 的dataset_version；默认v1，可改为v0。本机可用 `/opt/VisionStudio/runtime/bin/python`。

```bash
# 只读检查 canonical 数据，JSON 输出到 stdout；失败退出非零
python -B script/repository/verify_dataset.py

# 为当前克隆生成配置；原始 dataset.yaml 不变
python -B script/repository/prepare_data.py
# 输出：experiments/configs/datasets/v1.dataset.yaml

# 从冻结 manifest 校验来源和现有副本，补齐缺失的独立副本
python -B script/repository/prepare_data.py --view holdout --dataset-version v1
# 输出：experiments/configs/datasets/v1/dataset.yaml 和五类本地名单

# 只检查，不创建配置、目录或副本
python -B script/repository/prepare_data.py --view holdout --dataset-version v1 --check-only
```

`current` 引用共享配置所选版本；默认v1有464张Test，v0的Test为空。运行YAML输出为 `experiments/configs/datasets/<版本>.dataset.yaml`，每次根据当前克隆根目录重新生成。`holdout` 使用选定版本的 `source_version` / `manifest_id`，从来源版本图片和label按冻结manifest校验原split、文件名、SHA256，恢复当前版本内缺失副本；默认v1来源为v0。所有来源、已存在副本、审核字段与分配均先全量检查；任何不一致会在复制前失败，不覆盖已有文件。软链接和与来源共用 inode 的副本也会被拒绝。复制过程失败时保留已完成且哈希正确的副本，再运行可继续补齐。

生成的名单使用当前克隆的绝对路径，YAML 仅引用 train/val/test。buffer、heldout_unused 名单可供追溯，不进入训练配置；原 250 张 excluded 不复制。冻结的 YAML、名单、manifest、metadata 和历史报告均不改写。本地配置写入 `experiments/configs/`，迁移仓库后重新生成。`--check-only` 不要求已存在本地配置；发现缺失副本时报告 `missing_copies` 并退出 1，其余校验失败同样退出非零。

训练与评估入口默认也跟随共享配置，无需另外传data。若要显式指定数据配置（会覆盖共享选择），可运行：

```bash
python script/model-training/train.py --data experiments/configs/datasets/v1.dataset.yaml --dry-run
# 单类模型评估；模型路径换成实际训练结果
python script/model-evaluation/evaluate.py --model experiments/train/你的实验/weights/best.pt \
  --data experiments/configs/datasets/v1/dataset.yaml --split test --dry-run
```

holdout 是同一场次片段留出，不能代替独立场次测试。已有权重曝光史未知；准备文件和读取检查不代表已完成训练、推理或性能评估。冻结的从零训练示例含原机器绝对路径，迁移后不要直接运行；使用训练工具自己的配置并显式指定本地架构、新数据配置及 `pretrained: false`。

`--dataset-config` / `--dataset-version` 可覆盖本次选择；原始版本中的冻结YAML、名单、manifest不改写。没有excluded记录的版本无需伪造空的隔离manifest。

校验器检查 metadata 唯一性、审核状态、active/excluded 路径与配对、场景字段、No Ball 与空 label、class 0 的五列有限归一化坐标和边界。excluded 只检查隔离清单、历史字段和文件 SHA256；其保留的异常参考 label 会计数，不当作可训练标注。图片检查覆盖存在性和非空，不解码像素，也不重新进行人工审核、感知去重或来源独立性审计。

```bash
python -B -m unittest discover -s script/repository/tests -v
```
