# E00：原模型足球检测参考

E00评估已有的80类YOLO26s参考权重，没有新增训练；选择模型class32 `sports ball`映射为数据class0 `football`。完整 `datasets/v1` Val 评估已完成。

公开证据：[评估报告](evaluation/REPORT.md)、[结构化指标](evaluation/metrics.json)、[输入来源](evaluation/inputs_manifest.json)、[实验摘要表](../../benchmarks/experiment_tables/E00.md)。后续E01单类微调对照见 [E01/E02报告](../../benchmarks/E01_E02_REPORT.md)。

评估使用CPU单线程、batch4、640、FP32 one-to-many、外部NMS；候选下限0.001、工作conf0.25、匹配IoU0.5、NMS IoU0.7、max_det300。它在该Val上预测保守、漏检多；无球误报为零不代表对所有场景均无误报。

报告里的旧模型绝对路径是历史身份；当前参考资产说明见 [baseline](../../baseline/README.md)。此处公开的Val产物不意味着其它实验的忽略run也随克隆提供。共享评估入口及复现前提见 [复现说明](../../docs/REPRODUCIBILITY.md)。
