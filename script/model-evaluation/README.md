# 足球检测模型评估

输入一个本地检测模型，评估指定集合中已完成审核的足球图片，输出量化指标、逐图错误清单和论文图表。只读取原模型/原图/label/metadata，不训练模型、不改数据、不在数据集内写Ultralytics缓存。

## 快速使用

本机推荐使用交互式启动脚本，运行后在终端粘贴模型路径并回车：

```bash
bash /home/misaka/workspace/script/model-evaluation/evaluate.sh
```

默认评估Val，使用 **GPU 0**，优先选择本机 `~/.local/share/vision-studio/gpu-runtime/bin/python`（PyTorch 2.9.1+cu128）。`--device cpu` 切换CPU，此时默认使用 `/opt/VisionStudio/runtime/bin/python`。CPU计算线程默认限制为1。模型路径支持空格、成对的外层引号和 `~/`；**交互输入的相对模型路径以当前终端目录解析**。其他评估参数可追加到脚本命令后，例如：

```bash
# 切换CPU
bash script/model-evaluation/evaluate.sh --device cpu
# 只预检查，不执行推理（跳过CUDA可用性检查）
bash script/model-evaluation/evaluate.sh --dry-run
# 默认只输出PNG；需要其他格式时在命令行指定
bash script/model-evaluation/evaluate.sh --formats svg
bash script/model-evaluation/evaluate.sh --formats pdf
# 同时输出多个格式
bash script/model-evaluation/evaluate.sh --formats png,svg,pdf
# 使用COCO参考模型时，输入baseline/original_best.pt并明确选择足球类别32
bash script/model-evaluation/evaluate.sh --class-id 32
# 使用自己的GPU环境
FOOTBALL_EVAL_PYTHON=/你的环境/bin/python bash script/model-evaluation/evaluate.sh --device 0
```

`FOOTBALL_EVAL_PYTHON` 的显式设置优先；否则GPU模式优先用本机CUDA环境，再尝试预置CPU环境或 `python3`。正式评估前会检查依赖、PyTorch CUDA构建和设备可见性：环境不支持所请求GPU时立即报错，不会静默改用CPU，也不会先扫描数据集或创建失败结果目录。可通过 `FOOTBALL_EVAL_PYTHON` 指定自己的环境。输入路径不存在时会提示重新输入，按Ctrl+C退出。`bash script/model-evaluation/evaluate.sh --help` 查看全部评估参数。

以下示例从克隆后的仓库根目录运行，`python` 指向已准备好依赖的环境。脚本也可通过完整路径从任意工作目录调用；命令行中模型、数据、metadata和输出相对路径均基于仓库根目录，支持绝对路径和 `~`。

先按硬件准备PyTorch，再安装本目录依赖：

```bash
python -m pip install -r script/model-evaluation/requirements.txt
```

本机GPU环境为 `~/.local/share/vision-studio/gpu-runtime/bin/python`，核验版本是Ultralytics 8.4.173、PyTorch 2.9.1+cu128；CPU环境为 `/opt/VisionStudio/runtime/bin/python`，安装PyTorch 2.9.1+cpu。直接运行下方Python命令时，请按设备选择对应解释器。启动脚本 `evaluate.sh` 会自动选择。

```bash
# 输入你已经训练好的单类football模型；请换成实际存在的best.pt
python script/model-evaluation/evaluate.py \
  --model /你的训练结果/weights/best.pt

# 调整尺寸、工作阈值和设备；GPU须使用有对应CUDA/TensorRT依赖的Python环境
python script/model-evaluation/evaluate.py \
  --model experiments/train/football_yolo26s/weights/best.pt \
  --split val --imgsz 640 --conf 0.25 --device 0 --batch 4

# 当前参考权重是COCO 80类：0=person，32=sports ball，须显式选32
python script/model-evaluation/evaluate.py \
  --model baseline/original_best.pt --class-id 32 --split val --device cpu

# 只检查当前集合、标签和审核状态：不会加载模型、不会创建评估结果目录
python script/model-evaluation/evaluate.py \
  --model baseline/original_best.pt --class-id 32 --dry-run
```

默认数据版本由 [../config.yaml](../config.yaml) 的 `dataset_version` 决定，每次启动重新读取，无需重新编译。当前默认v1：Train 4346、Val 1223、Test 464；v0：Train 6925、Val 1223、Test为空。默认集合为 **val**。v1的Test是同场次片段留出，不能当作独立场次测试；v0执行 `--split test` 会报错而不回退到Val。`--dataset-version v0` 可临时覆盖版本；`--data` 可显式指定其他YAML，此时不再跟随共享选择。

如使用自己的环境：先按硬件准备PyTorch，再 `python -m pip install -r script/model-evaluation/requirements.txt`。要求Python 3.10+，Ultralytics支持YOLO26；ONNX/TensorRT/TorchScript需自行准备对应运行时。脚本禁用Ultralytics自动安装，不自动下载模型。支持Ultralytics兼容的 `.pt`、`.onnx`、`.engine`、`.torchscript` **检测模型**；本机完整运行测试覆盖PT（含GPU实际推理），其余格式依赖实际导出模型和设备。导出模型的固定输入尺寸、batch和量化精度以其自身为准。

## 指标口径

| 指标 | 计算方式 |
| --- | --- |
| mAP50、mAP75 | 目标匹配IoU分别0.50、0.75的AP；本项目只有一个GT类别 |
| mAP50–95 | IoU=0.50:0.05:0.95的10项AP平均 |
| Precision、Recall、F1 | 在预先指定 `--conf` 和 `--match-iou` 下，过滤候选后重新一对一匹配 |
| TP、FP、FN | 同一固定工作点的目标级计数，单个框最多匹配一个GT |
| 无球图片误报率 | **有至少一个超过工作阈值的football框的无球图片数 / 确认无球图片总数** |
| 无球每图误报框数 | 无球图误报框总数 / 无球图片数；和“图片误报率”分别报告 |
| FPPI | 全部图片上的误报框总数 / 图片数 |
| 有球图片漏检率 | 有GT球但没有任何正确匹配球的图片数 / 有球图片数 |

一张无球图有3个误报框时，“误报图片”只计1张；另外保留3个误报框的计数。无负样本时FPR是 `null/N/A`；无GT球时AP、Recall是 `null/N/A`，不会伪装成0或成功。输出无球FPR的Wilson 95%描述性区间；由于左右目/邻帧相关，这不是按独立视频分组计算的统计置信区间。

AP调用安装版本的官方 `ultralytics.utils.metrics.ap_per_class`；一对一匹配与官方 `BaseValidator.match_predictions` 默认算法对照测试。采用101点插值及精度包络，**不等同于包含面积分层/crowd规则的完整COCO评测**。只输出单类football的AP，不输出其他COCO类别的平均值。

AP/P-R使用 `--min-conf`（默认0.001）以上的全部候选；固定工作阈值默认 `--conf 0.25`，这两个值不同。**不要为了部署阈值而把min-conf也提高到0.25，否则会截断AP的召回范围。** `metrics.json`里额外的 `ultralytics_max_f1_precision/recall` 是官方AP扫阈值摘要，和主表固定阈值P/R不同；不要在Test上选择最佳阈值。

一次调用 `YOLO.predict(stream=True)` 获得候选，使用临时txt名单按批次读取图片，避免把全部原图一次性加载到内存。使用 `rect=False` 方形letterbox、不启用TTA；与默认 `model.val(rect=True)` 的几何处理可能不同，所以比较其他实验时必须统一尺寸、letterbox、候选阈值、NMS/模型头模式、max_det、精度和设备。报告保存实际加载器、batch、设备、FP16和end-to-end状态；NMS-free导出模型的候选限制由其模型本身决定。参考：[官方验证参数与口径](https://docs.ultralytics.com/modes/val/)、[官方指标API](https://docs.ultralytics.com/reference/utils/metrics/)。

## 输出

默认新建 `experiments/eval/<模型名>_<split>_<UTC时间>_<随机后缀>/`；可用 `--output` 指定另一个**尚不存在**的新目录，拒绝覆盖和在原数据集内输出。

```text
结果目录/
├── status.json                  # running/complete/failed，判断运行是否完成
├── metrics.json                 # 总体+场景指标、版本、参数、计时
├── REPORT.md                    # 中文口径与可读结果表
├── inputs_manifest.json         # 模型/数据/代码SHA256、实际评估清单
├── predictions.jsonl            # 全部低阈值候选与GT，非仅工作阈值框
├── per_image.csv                # 每图TP/FP/FN、预测框数、四项场景
├── false_positive_no_ball.csv   # 无球误报清单；零误报时只含表头
├── figures/                     # 默认仅PNG（300dpi）；--formats可改为SVG/PDF等
└── tables/
    ├── pr_curve.csv             # AP50精度包络的原始坐标，有GT时输出
    ├── confidence_curves.csv    # 固定IoU下逐置信度重匹配的P/R/F1/FPR等
    ├── ap_by_iou.csv            # 10个匹配IoU的AP
    ├── scene_metrics.csv        # All/四项场景/无上述困难场景
    └── paper_row.tex            # 可复制到论文LaTeX表格的数值行，比例为0–1
```

默认只输出PNG（300dpi）。用 `--formats svg` 或 `--formats pdf` 切换格式，也可用 `--formats png,svg,pdf` 同时输出多个格式。`scene_comparison` 在每个有效柱子上方标注保留两位小数的百分数，例如 `99.50%`、`0.00%`；纵轴同样显示百分数，未定义指标显示NA。JSON/CSV中的指标仍以0–1比例保存。

生成8类图：P-R曲线，P/R/F1–Confidence曲线，无球误报率–Confidence曲线，AP–IoU曲线，FROC（Recall–FPPI），目标检测混淆矩阵，图像存在性混淆矩阵，场景指标对比图。论文图坐标/标签使用英文、嵌入PDF字体，SVG保留文字，可直接用于LaTeX或矢量编辑。

目标级背景TN没有定义，检测混淆矩阵对应单元显示N/A；图像存在性矩阵有合法TN，但“预测存在球”不保证定位正确。四个场景可重叠，不能把分组样本数相加，不能简单平均子集AP当总体AP。场景表中NA保持为空指标，而不是0分。

计时包括后端报告的预处理/推理/后处理均值，以及含加载和首次warmup的预测墙钟吞吐；**这不是经过独立硬件benchmark流程测出的纯推理FPS**。

## 数据检查

默认按所选版本的 `images/{train,val,test}` 生成本机运行YAML到 `experiments/configs/datasets/`，不使用原冻结YAML/名单里的旧绝对路径，也不改写它们。预检查同样可能生成运行YAML；只有指定 `--data` 时直接使用给定YAML。详见[共享配置说明](../common/README.md)。

- 读取数据集YAML的目录或图片名单，图片须采用 `images/…` 与 `labels/…` 的镜像目录关系。
- YAML中相对 `path` 以YAML文件所在目录解析，split相对该根目录，txt名单内部路径相对名单所在目录；本项目现有path为绝对路径。
- 默认使用共享配置所选根目录的 `metadata.csv`，可用 `--metadata` 指定。只选 `reviewed_annotation` / `negative_confirmed` 且两项审核标志均为0的样本，跳过 `reviewed_excluded` 和未完成审核项。
- 有效样本的缺label、越界/非有限坐标、非0类别、No Ball/审核状态冲突、目录与metadata.split不一致均报错；不会偷偷将缺失标签当成无球。
- 多类模型必须显式给 `--class-id`，仅该类别的预测映射为GT的0=football。单类默认其唯一类别，名称和选择ID写入manifest，调用者应确保它代表足球。
- 结束后重查输入模型、图片、label、YAML、metadata的SHA256；来源变化则status=failed，不发布完整成绩。预测失败/部分图片失败也不会跳过样本偷偷报完整成绩。

## 参数与复现

```bash
python script/model-evaluation/evaluate.py --help
# 仅调试：这不是完整Val结果；--limit按文件名选择前N张，不随机抽样
python script/model-evaluation/evaluate.py --model /模型/best.pt --limit 20 --imgsz 320 --device cpu
# 指定新输出、论文格式与分辨率
python script/model-evaluation/evaluate.py --model /模型/best.pt \
  --output experiments/eval/experiment_A --formats png,pdf,svg --dpi 300
```

其他参数：`--batch 4`、`--threads 1`、`--min-conf .001`、`--conf .25`、`--match-iou .5`、`--nms-iou .7`、`--max-det 300`。默认限制CPU为1线程；不启动额外数据加载进程。设 `--limit` 时会在报告中标明是否只评估了部分集合，不能拿调试分数写成完整集合结果。

验证代码：

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  python -B -m unittest discover -s script/model-evaluation/tests -v
```

测试覆盖审核过滤、空Test拒绝、空框/缺框区分、No Ball冲突、输入变化保护、类别映射、双球和重复框匹配、无球图片/框计数分母、零分母、官方匹配对照及图表/CSV/LaTeX一致性；不以虚构预测替代真实模型的完整数据集结果。
