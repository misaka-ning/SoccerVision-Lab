# 足球模型训练

统一入口 `train.py` 读取 `config/train.yaml`，默认使用仓库内的 YOLO26s
参考权重 `baseline/original_best.pt`，在 [../config.yaml](../config.yaml) 选择的数据版本上微调；默认v1。
参考权重包含 80 类，数据集目标为 `0 = football`；Ultralytics 根据数据集重建单类检测头并迁移兼容权重。

## 安装与运行

建议使用 Python 3.10–3.12 的独立环境。先按硬件安装相应的 PyTorch，再安装本目录依赖；
不要根据旧 checkpoint 内的 `8.3.222` 元数据锁定运行时版本，运行时必须支持 YOLO26。

以下命令从克隆后的仓库根目录执行，`python` 指向已准备好依赖的环境：

```bash
python -m pip install -r script/model-training/requirements.txt

# 只检查配置和文件存在性，不需要 torch/ultralytics，但需要 PyYAML
python script/model-training/train.py --dry-run

# 按默认 YAML 开始训练
python script/model-training/train.py

# 自定义配置，或用命令行覆盖常用参数
python script/model-training/train.py --config script/model-training/config/train.yaml --device 0 --epochs 150 --batch 8 --imgsz 960 --name football_960

# 使用数据准备步骤生成的本地数据集配置，先检查再训练
python script/model-training/train.py --data experiments/configs/datasets/v1.dataset.yaml --dry-run
python script/model-training/train.py --data experiments/configs/datasets/v1.dataset.yaml

# CPU 小规模运行示例
python script/model-training/train.py --device cpu --epochs 1 --batch 2 --imgsz 320 --name smoke

# 从中断实验的 last.pt 继续；路径按实际实验目录修改
python script/model-training/train.py --resume experiments/train/football_yolo26s/weights/last.pt --device 0
```

`--config` 相对当前工作目录；配置内 `model`、`data`、`project` 和字符串形式的
`pretrained`，以及 `--data`、`--resume` 路径，均相对仓库根目录，也支持绝对路径。
默认配置不依赖启动时所在目录。模型必须是已存在的本地 `.pt` / `.yaml` 文件。
改用 `baseline/original_model.yaml` 可从架构初始化；若要同时迁移参考权重，在配置中增加
`pretrained: baseline/original_best.pt`。仅改架构文件则从随机权重开始训练。

断点续训使用 checkpoint 保存的训练参数及优化器状态，只接受额外的 `--device` 覆盖。
如需修改训练轮数、数据或超参数进行新实验，将 `model` 改为已有权重并正常启动训练。

## 数据与结果

- 默认训练配置 `data: null`，每次启动重新读取共享 `dataset_version`，生成本机运行YAML到 `experiments/configs/datasets/<版本>.dataset.yaml`；修改版本无需重新编译。预检查也会生成运行YAML，但不启动训练，不改原始版本YAML或名单。版本中的正式images/labels目录须与分集一致；reserved/excluded不纳入。
- `--dataset-config` / `--dataset-version` 可临时覆盖共享选择；若训练配置中data非空或给了 `--data`，则优先使用显式数据路径，不跟随共享选择。修改版本应新开训练；`--resume` 继续使用checkpoint原参数。
- 正式训练前完成图片和标注审核。脚本使用 YAML 对应 split 的全部样本，
  **不会根据 `metadata.csv` 自动过滤待审核样本**，也不会把缺失标注修复为无球。
  如只训练已审核子集，请另建数据集 YAML 并修改 `data`。
- 预检查只验证基本参数和配置文件，不加载 checkpoint，不检查 CUDA、每张图片或标注；
  完整模型与依赖兼容性需要实际训练验证。首次训练还可能由框架下载辅助权重。
- 默认输出到 `experiments/train/football_yolo26s/`，含 `weights/best.pt`、
  `weights/last.pt`、`args.yaml`、`results.csv` 和图表。重复运行自动使用递增目录。
- 更多参数可直接加入训练 YAML，名称与
  [Ultralytics 官方训练参数](https://docs.ultralytics.com/modes/train/) 一致；
  未知参数由 Ultralytics 校验。续训统一使用 `--resume`，不要在 YAML 中嵌套 `cfg`。

## 验证脚本

```bash
python -m unittest discover -s script/model-training/tests -v
```

测试覆盖路径解析、配置覆盖、续训参数和训练调用，使用模拟模型，不启动训练或下载权重。
