# 脚本目录说明

本目录包含足球数据集审阅、模型训练、模型评估和数据校验工具。各工具默认共用 [config.yaml](config.yaml) 选择数据版本，公共配置代码集中在 `common/`。

## 文件夹用途

| 文件夹 | 主要作用 | 常用入口 |
| --- | --- | --- |
| [common/](common/README.md) | 读取共享YAML，解析当前数据版本和路径，生成本机YOLO运行配置；保存公共依赖及版本切换测试 | `dataset_config.py`；通常由其他工具自动调用 |
| [dataset-reviewer/](dataset-reviewer/README.md) | Qt人工审阅工具：每页50张平铺、查看和修改足球框、调整四类场景、确认审核状态、导出已审核数据 | `review_dataset.sh` |
| [model-training/](model-training/README.md) | 按训练YAML启动YOLO训练，设置模型、轮数、输入尺寸等参数，并支持断点续训 | `train.py`；训练参数在 `config/train.yaml` |
| [model-evaluation/](model-evaluation/README.md) | 输入检测模型，计算mAP50、mAP50–95、Precision、Recall、F1、无球图片误报率，并生成P-R曲线等论文图表 | `evaluate.sh`，在终端提示输入模型路径；也可用 `evaluate.py` |
| [repository/](repository/README.md) | 检查数据集结构、图片与label配对、场景及审核字段；生成本机运行配置，校验或补齐冻结留出版本的独立副本 | `verify_dataset.py`、`prepare_data.py` |

## 选择数据版本

编辑 [config.yaml](config.yaml) 中这一行：

```yaml
dataset_version: v1  # 改为v0即可选择datasets/v0
```

保存后重新运行工具即可生效，**无需因修改数据版本重新编译Qt程序**。已经打开的窗口或正在运行的训练不会中途切换。

配置中的路径相对仓库根目录解析。当前v0的Test为空；v1有Test，但属于同场次片段留出。正式使用的范围为所选版本的 `images/{train,val,test}` 与对应 `labels/`，不自动包含reserved或excluded。

训练配置中的 `data: null` 表示跟随共享选择。显式传入 `--data`、`--dataset` 或将训练配置中的data设为具体路径时，使用显式指定的数据；断点续训保留checkpoint原参数，更换版本应启动新训练。

## 常用启动方式

以下命令在仓库根目录执行：

```bash
cd /home/misaka/workspace
```

Python示例使用本机现有的 `/opt/VisionStudio/runtime/bin/python`；其他机器请替换为已安装对应依赖的Python环境。

### common：查看当前选择

通常不需要单独运行公共组件。需要核对配置时可执行：

```bash
/opt/VisionStudio/runtime/bin/python -B script/common/dataset_config.py
```

输出所选版本、数据根目录、metadata路径等信息。共享Python/Shell读取器的用法及依赖见 [common说明](common/README.md)。

### dataset-reviewer：人工审阅

```bash
# 打开当前版本，每页最多50张平铺
bash script/dataset-reviewer/review_dataset.sh --gallery
```

需要本机Qt SDK及构建环境，首次运行会自动构建。保存审核时会更新所选数据集的metadata，修改球框还会更新对应label。旧的1000张固定审核批次属于v0，不能直接用于v1；批次入口及快捷键见 [审阅说明](dataset-reviewer/README.md)。

### model-training：训练模型

先修改 [训练参数](model-training/config/train.yaml)，再执行：

```bash
# 只检查配置，不启动训练
/opt/VisionStudio/runtime/bin/python -B script/model-training/train.py --dry-run

# 本机CPU训练；使用GPU时换为对应环境，并按需设置--device 0
/opt/VisionStudio/runtime/bin/python -B script/model-training/train.py --device cpu
```

训练结果默认保存在仓库的 `experiments/train/`。训练不会按metadata中的审核标志自动过滤图片，使用前应确认所选集合可用于训练。模型、超参数及续训方式见 [训练说明](model-training/README.md)。

### model-evaluation：评估模型和生成图表

```bash
bash script/model-evaluation/evaluate.sh
```

按提示输入模型路径，默认评估Val，使用GPU 0，并自动优先选择本机CUDA环境。追加 `--device cpu` 可改用CPU；正式运行前会检查环境和GPU可用性。需要评估Test时运行：

```bash
bash script/model-evaluation/evaluate.sh --split test
```

结果默认保存在 `experiments/eval/`，包括Markdown报告、JSON/CSV指标、逐图错误清单及默认PNG图表（可用 `--formats svg` / `--formats pdf` 切换）。若输入 `baseline/original_best.pt` 这个COCO多类参考模型，应在启动命令后加 `--class-id 32`。完整指标口径和参数见 [评估说明](model-evaluation/README.md)。

### repository：校验和准备数据

```bash
# 只读检查当前选择的数据版本
/opt/VisionStudio/runtime/bin/python -B script/repository/verify_dataset.py

# 生成适配当前本机路径的运行YAML
/opt/VisionStudio/runtime/bin/python -B script/repository/prepare_data.py
```

运行YAML位于 `experiments/configs/datasets/`。训练和评估默认会自动生成所需配置，一般不必手动准备；版本内原有YAML、名单及manifest保留历史内容。冻结副本恢复及只读预检方式见 [仓库工具说明](repository/README.md)。
