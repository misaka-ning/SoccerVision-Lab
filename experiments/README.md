# 实验设计与独立运行

当前实验入口：

|目录|状态|
|---|---|
|`E00_original/`|原始模型参考与已有评估记录|
|[E01_baseline](E01_baseline/README.md)|单类别足球微调与 Val 已完成，建立 E1 基线；原目录由用户重命名至此|
|[E02_c3k2](E02_c3k2/README.md)|第19层隐藏通道128→112；78轮恢复训练和独立 Val 已完成，Orin 三轮对照未取得可测量加速收益|
|[E03_tensorrt_profiling](E03_tensorrt_profiling/README.md)|已完成实机 Profiling、原始结果回收与校验；Top20/模块/L19/Nsight/系统结论见报告|
|[E04_tensorrt_pipeline](E04_tensorrt_pipeline/README.md)|推理链路优化；100个有效性能作业与组合Golden已审查，R4同期系统约+6.93%；后续用户暂停，长稳/生产采用未验收|
|[E05_yolo26n](E05_yolo26n/README.md)|nano73轮、最佳43轮；完整独立Val mAP50-95为76.846%，E01为78.567%；召回下降，无球误报更少；转入E06，未做Orin测速|
|[E06_distillation](E06_distillation/README.md)|KD1：冻结E01-s教师、与E05同起点nano，原生P3/P4/P5特征蒸馏dis=6；独立入口与短时验证，正式训练待用户启动|
|[E07_warmstart_distillation](E07_warmstart_distillation/README.md)|WarmKD：从E05 best.pt开始，教师与训练配方同E06；独立run、共享GPU互斥，正式训练待用户启动|

阶段结果见[E00～E03实验表格](../benchmarks/experiment_tables/README.md)及[E1/E2 实验报告](../benchmarks/E01_E02_REPORT.md)，包含实验内容、产出、精度变化、实机结论及比较范围。

E03 已用于 TensorRT Profiling；后续 P2、Neck 或系统优化按实际假设另行编号，不复制多套训练/评估实现。原架构已经包含C3k2，E02是指定层内部宽度试验。运行管理信息保存在各run的 `run_record.json`；历史组织设计见[实验设计](../reports/workspace-organization/EXPERIMENT_DESIGN.md)，其中旧路径和“未训练”描述为当时状态，当前以各实验记录和追加汇总为准。

## 每次运行

- 一个实验ID管理同一研究假设；一个独占新建的 `runs/<UTC>_s<seed>_<suffix>/` 管理一次运行。已存在ID即停止，不覆盖best.pt、last.pt、results.csv。
- 实验设计保存PLAN和小型architecture定义/引用；训练与评估实现仍用script内统一工具，不复制train.py/指标代码。
- 当前工具仍按既有约定写train/、eval/、configs/；先在run记录中引用其实际输出。新树不意味着代码已经支持自动写入/封存该目录。
- 复制模板到新的run后填写实际结构、初始化、有效配置、数据版本/内容哈希、源码状态和环境。未执行项保持null/not_run；没有best选择或部署测量时不填假0。
- 模型参数量与FLOPs保留输入shape、计算工具/版本、乘加口径。Val记录所有开发选择；Test仅在最终候选/阈值冻结后正式评价，每次访问含失败都留痕。
- 部署记录导出hash、TensorRT/设备/驱动/精度/输入/power mode、warmup、同步与计时边界，不把普通评估吞吐当Orin部署延迟。
- 完成后冻结run事实，订正另追加记录。更改结构/数据/超参数的新训练是新run；恢复训练记录checkpoint SHA和恢复事件。

数据只引用 `datasets/v1` 的冻结版本和SHA，不给每实验复制图片；初始化引用baseline原权重hash，不覆盖原件。新初始化的Test曝光需按其自身来源填写，不能把原权重的确认套到所有权重。

正式完成的比较只把摘要和run引用加入[benchmarks](../benchmarks/README.md)。根 `.gitignore` 已忽略 `E*/runs/`、`train/`、`eval/` 和本机生成的 `configs/`；实验设计、小型配置及可审阅摘要保留在运行目录之外。新增输出路径仍需检查忽略规则，不能全量git add。许可未确认的图片/模型和恢复包不公开。
