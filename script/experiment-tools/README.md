# 实验审计辅助

`warm_control.py`供E08调用：冻结Train/Val视图、请求/有效配置差异、教师加载拦截、首步张量一致性、原生optimizer更新计数、训练CSV预算。

训练参数继续由`script/model-training/train.py`解析，训练/损失/早停由固定版本Ultralytics执行；独立指标继续复用`script/model-evaluation`。这里没有新的正式训练循环或AP算法。接受测试位于`experiments/E08_warmstart_no_distillation/tests/`。
