# 实验设计与独立运行

保留现有 `E00_original/`、`E01_baseline/` 空预留目录。未来按需创建E01_finetune、E02_c3k2、E03_p2、E04_neck；不一次性复制五套代码、数据和配置。原架构已有C3k2，E02须明确变体/层号；各结构实验先以E01为单因素对照。

本轮只增加一份[run_record.json模板](_template/run_record.json)，它是管理记录，不是训练配置或当前程序接口；未启动任何训练、推理、Test或部署。详细方法见[实验设计](../reports/workspace-organization/EXPERIMENT_DESIGN.md)。

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
