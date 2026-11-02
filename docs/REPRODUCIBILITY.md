# 复现入口与证据可用范围

[首页](../README.md) · [全部实验](../experiments/README.md) · [结果摘要](../benchmarks/RESULTS.md) · [来源审查](SOURCE_AUDIT.md)

## 先选复现层级

|层级|可以做什么|必要材料与限制|
|---|---|---|
|阅读研究结果|查看计划、报告、表格及小型校验摘要|只需仓库文档；本次文档验收停留在这一层，不重新运行模型|
|检查配置/接口|共享配置查看、E08离线dry-run、CLI帮助|Python及PyYAML；不代表真实数据/模型/设备已经兼容|
|重复训练与Val|新建run、核对来源、smoke、用户手动训练和评估|冻结Train/Val、对应初始化、原run依赖/源码hash；部分材料只有本地引用|
|复算实机统计|对已回收CSV/trace运行CPU分析|对应完整原始包；仓库小型摘要不等于完整原始包|
|新的部署测量|导出正确性、设备独立构建、系统A/B、长稳|匹配的设备/runtime/Engine/场景、独立测试窗口；不由文档命令自动触发|

## 环境与工具入口

E01/E02/E05–E07报告的训练环境为Python3.10.12、Torch2.9.1+cu128、Ultralytics8.4.173、RTX4060。E08 CPU工程smoke使用Torch2.9.1+cpu/Ultralytics8.4.173；真实CUDA流程not_run。E03/E04实机使用Orin NX 16GB、JetPack5.1.5、TensorRT8.5.2.2；E04执行环境为Python3.8.20、Torch2.0.0+nv23.05、Ultralytics8.3.159。不同环境不能互换，版本号也不能替代源码hash。[模型报告](../experiments/E07_warmstart_distillation/REPORT.md) · [E08检查](../experiments/E08_warmstart_no_distillation/VALIDATION.md) · [E04环境](../experiments/E04_tensorrt_pipeline/REPORT.md)

通用安装说明在[训练工具](../script/model-training/README.md)、[评估工具](../script/model-evaluation/README.md)和[Qt工具](../script/dataset-reviewer/README.md)。历史实验复现以其冻结环境为准，不因为依赖文件有宽松约束就升级。绝对路径`/opt/VisionStudio/...`及`/home/...`是原工作站示例，迁移后用自己的兼容解释器和新run。

以下从仓库根目录执行，不启动训练：

```bash
# 仅读取共享配置
python script/common/dataset_config.py
# 纯配置预览，不加载权重或图片
python experiments/E08_warmstart_no_distillation/e08.py dry-run
# 了解实际参数
python script/model-training/train.py --help
python script/model-evaluation/evaluate.py --help
```

完整操作按对应入口进行，不将通用默认值当作某实验配方：

|阶段|实际入口|说明|
|---|---|---|
|人工框/场景审核|[数据工作流](DATA_WORKFLOW.md)|保存会修改所选工作数据；冻结v1不能原地修订|
|版本配置与路径适配|[script/common](../script/common/README.md)、[script/repository](../script/repository/README.md)|工具可能遍历整个所选版本；阅读检查不要执行全量数据校验|
|E01/E02训练|[E01计划](../experiments/E01_baseline/PLAN.md)、[E01编排](../experiments/E01_baseline/e01.py)、[E02入口](../experiments/E02_c3k2/README.md)|E01只有本地详细复现run；E02候选与原结构control分开|
|nano/KD|[E05](../experiments/E05_yolo26n/README.md)、[E06](../experiments/E06_distillation/README.md)、[E07](../experiments/E07_warmstart_distillation/README.md)|报告已完成的run不可再次启动覆盖；新假设新run|
|无KD继续训练|[E08完整命令](../experiments/E08_warmstart_no_distillation/README.md#用户启动命令)|prepare核验E07实际配置/库/数据及E05 best；缺历史run直接停止；真实smoke后才可手动train|
|独立Val与阈值分析|[共享评估](../script/model-evaluation/README.md)|明确`--split val`及对应工作阈值；dry-run仍会检查所选图片/标注，不等于纯配置检查|
|实机归档复算|[E03](../experiments/E03_tensorrt_profiling/README.md#分析复现)、[E04](../experiments/E04_tensorrt_pipeline/REPRODUCE.md)|仅在取得原始包后重算，保留计时/统计边界|
|导出与构建|[E05导出说明](../experiments/E05_yolo26n/README.md)|工具入口存在不等于正式训练后ONNX/TRT或系统验收已完成|

Test不在首页快速命令中。冻结候选和阈值后才考虑正式Test协议，记录每次访问；v1是同场次留出，另采独立场次才能回答独立泛化问题。

## 公开摘要与本地产物

“公开摘要”表示已跟踪、可通过仓库网页阅读，不承诺仓库或资产具有开放许可证。本地引用保留路径身份，用代码格式呈现而不制造GitHub死链接。路径中的`<repo>`表示保存原run的工作站仓库根目录，不是本次克隆自动生成的文件。

|实验/材料|网页可读摘要|本地产物引用（未随Git提供的部分）|
|---|---|---|
|E00|[报告](../experiments/E00_original/evaluation/REPORT.md)、[metrics](../experiments/E00_original/evaluation/metrics.json)|E00的evaluation小型结果已跟踪；报告内旧绝对路径代表原位置|
|E01|[E01/E02报告](../benchmarks/E01_E02_REPORT.md)、[E01表](../benchmarks/experiment_tables/E01.md)|`<repo>/experiments/E01_baseline/runs/20261019T092432Z_s42_853c4a/`，含RESULT.md、E00_VS_E01.md、REPRODUCE.md、evaluation/与训练产物|
|E02|[实验结果](../benchmarks/E01_E02_REPORT.md)、[E02表](../benchmarks/experiment_tables/E02.md)|`<repo>/experiments/E02_c3k2/runs/20261020T102957Z_s42_da66b0_candidate/`；Val为`<repo>/experiments/eval/best_val_20261021T025306Z_00e792/`|
|E03|[完整报告](../experiments/E03_tensorrt_profiling/REPORT.md)、[小型结果索引](../experiments/E03_tensorrt_profiling/results/README.md)|`<repo>/experiments/E03_tensorrt_profiling/runs/20261021T080741Z_824b47/`；大型result_bundle.tar.gz与机器人同名run|
|E04主实验|[阶段报告](../experiments/E04_tensorrt_pipeline/REPORT.md)、[RAW_DATA_INDEX](../experiments/E04_tensorrt_pipeline/RAW_DATA_INDEX.md)|`<repo>/experiments/E04_tensorrt_pipeline/runs/20261022T020842Z_78f1b7/`及其中各phase原始包|
|E04后续|[接入](../experiments/E04_tensorrt_pipeline/integration/E01_a2_graph_20261022T103907Z/INTEGRATION_REPORT.md)、[MAXN筛选](../experiments/E04_tensorrt_pipeline/preprocess_race/20261023T014627Z/REPORT.md)|报告含部分已跟踪安装/回收摘要；机器人应用目录与备份绝对路径仅为历史身份，不是远程控制入口|
|E05|[报告](../experiments/E05_yolo26n/REPORT.md)|`<repo>/experiments/E05_yolo26n/runs/20261023T023231Z_s42_90bcea/`；两模型Val在其`val_0p45_20261023T032229Z/`|
|E06|[报告](../experiments/E06_distillation/REPORT.md)|`<repo>/experiments/E06_distillation/runs/20261023T034325Z_s42_KD1_f1347d/`；完整Val引用E07归档|
|E07|[统一报告](../experiments/E07_warmstart_distillation/REPORT.md)|`<repo>/experiments/E07_warmstart_distillation/runs/20261023T035555Z_s42_WarmKD_93e0cf/`；四模型结果在`val_0p45_20261023T061225Z_e643a0/`，另有zero_area_v1评估修订|
|E08|[实现验收](../experiments/E08_warmstart_no_distillation/VALIDATION.md)、[JSON摘要](../experiments/E08_warmstart_no_distillation/VALIDATION.json)|`<repo>/experiments/E08_warmstart_no_distillation/runs/review_cpu_smoke_01/`、`review_cpu_smoke_02/`及`review_validation/`是工程检查，不是正式训练|

`models_list/`和`baseline/`中存在的发布权重不等于完整训练包。复现还需实际配置、数据身份、库实现与源文件；E08不能只凭发布的best权重绕过E07冻结配置校验。本文不下载、加载、移动或改写任何模型资产。

## 如何解释历史状态

按事件和证据读取，不用晚写的综合描述抹去原始限制：E04阶段性能、后续安装、MAXN筛选是不同事件；综合报告里的nano现场频率观察尚缺完整归档。E05报告中“当前不能判断”等句对应早期回收点，后续独立Val已追加；E06/E07报告的准备阶段smoke不等于其正式训练数字。E08实现验收则确实尚未进入正式训练。[逐项冲突与处理](SOURCE_AUDIT.md)
