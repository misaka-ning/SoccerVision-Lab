# 技术阅读入口

这条路线只索引已有实验及实现；模型质量与系统吞吐分别比较。先读 [实验总览](../experiments/README.md)，再选择下面一条证据链。

|研究问题|实验设计 → 结果|局限 → 代码|
|---|---|---|
|足球微调能否减少漏检？|[E00/E01 设计与结果](../benchmarks/RESULTS.md)：原模型参考与单类微调在同一开发 Val 比较。|类别数与训练同时变化，不能归因于单一因素；[共享训练入口](../script/model-training/train.py)、[评估入口](../script/model-evaluation/evaluate.py)。|
|参数减少会带来实机加速吗？|[E02 缩窄](../experiments/E02_c3k2/README.md) → [E03 Profiling](../experiments/E03_tensorrt_profiling/results/README.md)：L19 缩窄未取得可测量加速，局部执行反而更慢。随后 [E04 同期对照](../experiments/E04_tensorrt_pipeline/PERFORMANCE_COMPARISON.md) 支持 A2+Graph 收益，保留预处理负结果。|E02 原结构继续训练 control 无结果；参数量不能替代延迟。E04 固定设备/功耗/场景的帧对吞吐不能泛化为模型 FPS；[复算与代码定位](../experiments/E04_tensorrt_pipeline/REPRODUCE.md)。|
|蒸馏提高召回的代价是什么？|[E06 同初始化设计](../experiments/E06_distillation/README.md) → [E07 WarmKD 统一 Val 报告](../experiments/E07_warmstart_distillation/REPORT.md)：conf=0.45，E05/E07 AP50–95 为76.846%/77.540%，无球误报为4/410、7/410；E06 Small Recall 为92.340%，无球误报25/410。|单 seed 开发结果；E07 从 E05 best 继续训练，额外训练混杂尚未分离。[E08 同起点 NoKD 对照](../experiments/E08_warmstart_no_distillation/README.md)正式训练及新成绩仍为 `not_run`；[e08.py::config_for / effective_pair](../experiments/E08_warmstart_no_distillation/e08.py)、[compare.py::compare](../experiments/E08_warmstart_no_distillation/compare.py)核验配置与比较来源。|

这些质量成绩来自 **v1 开发 Val**，不是 Test。Test 是同场次片段留出，与 Train 共享采集场次，不证明独立场次泛化；阈值选择使用 Val，不在 Test 上挑最佳阈值。数据相关性、旧权重曝光和本地产物缺口见 [来源审计](SOURCE_AUDIT.md)、[复现边界](REPRODUCIBILITY.md)。本页不改写冻结实验、历史结果或生产配置。

训练和 AP 依赖既有 Ultralytics/PyTorch；本仓库的实验编排、来源核验、统一评估与报告组织可从上面的入口核查，不据此声称第三方模型或蒸馏算法为原创，也不推断人员分工。

## 五分钟 CPU 合成演示

**合成演示，非模型成绩，非性能基准。** [synthetic_demo.py::synthetic_records / demo](../script/model-evaluation/synthetic_demo.py)用代码生成4张虚拟图片的 GT 和预测框（xyxy）；不加载权重、不读图片或真实数据、不执行推理/NMS、不计时。

它直接调用 [eval_metrics.py::prepare → box_iou / match](../script/model-evaluation/eval_metrics.py) 和 `operating`。后者在 `score >= confidence` 筛选后重新做最高 IoU 一对一匹配：剩余预测含重复框均计 FP。没有复制指标算法，也不调用需要 Ultralytics 的 `average_precision / summarize`，因此不输出 AP。

Python **3.10–3.13**（NumPy 2.2.6 的支持范围），唯一第三方依赖 [NumPy 2.2.6](../script/model-evaluation/requirements-demo.txt)。从仓库根目录运行；所有环境、缓存、临时文件及输出显式放在本仓库（目录名也可选工作空间内的其他新目录）：

```bash
mkdir -p .demo-local/tmp .demo-local/cache
export TMPDIR="$PWD/.demo-local/tmp"
export XDG_CACHE_HOME="$PWD/.demo-local/cache"
export PIP_CACHE_DIR="$PWD/.demo-local/cache/pip"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python3 -m venv .demo-local/venv
.demo-local/venv/bin/python -m pip install --only-binary=:all: -r script/model-evaluation/requirements-demo.txt
.demo-local/venv/bin/python -B script/model-evaluation/synthetic_demo.py > .demo-local/output.json
.demo-local/venv/bin/python -B -m unittest discover \
  -s script/model-evaluation/tests -p test_synthetic_demo.py -v
cat .demo-local/output.json
```

不要安装完整评估的 `requirements.txt` 来运行本演示。无需 Torch/CUDA、GPU、账号或真实数据；首次安装 NumPy 需要包源网络。

固定匹配 IoU=0.5，预期主要输出如下（JSON 中比例为0–1）：

|置信度阈值|TP / FP / FN|Precision / Recall|无球误报图片 / 无球图片|无球误报框 / 无球图片|
|---|---|---|---|---|
|0.25|2 / 3 / 0|0.4 / 1.0|1 / 2 = 0.5|2 / 2 = 1.0|
|0.50|1 / 1 / 1|0.5 / 0.5|1 / 2 = 0.5|1 / 2 = 0.5|
|0.75|1 / 0 / 1|1.0 / 0.5|0 / 2 = 0.0|0 / 2 = 0.0|

第一张图在低阈值下有两个框争一个 GT，只能有一个 TP。其高 IoU 框分数0.4，另一个框分数0.9；阈值升至0.5后需重新匹配，仍有一个 TP。另一张有球图分数0.4，随后变为 FN。无球误报率按图片计，不能替换为误报框数。阈值变化不保证对真实模型产生相同趋势。

[独立测试](../script/model-evaluation/tests/test_synthetic_demo.py)断言上述计数、分母、阈值后重匹配、无分母时 `None`，并在 CLI 子进程阻止 Torch/Ultralytics/PIL 导入。更完整的官方匹配对照与 AP 测试在 [test_evaluation.py::MetricTests](../script/model-evaluation/tests/test_evaluation.py)，需要完整依赖，不属于本微型环境。

本次实际检查：Python 版本、安装、演示与测试结果记录见 [验证记录](TECHNICAL_READING_CHECKS.md)。
