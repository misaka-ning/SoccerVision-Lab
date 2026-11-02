# E04：TensorRT推理链路与后续接入

[全部实验](../README.md) · [分组结果摘要](../../benchmarks/RESULTS.md)

E04研究在不改变E01检测语义的前提下，减少双目结果回传、GPU任务提交及预处理开销。它包含多个有日期的阶段；**性能实验完成、代码安装、生产运行和长期验收不是同一状态**。

|阶段|已记录事实|边界与证据|
|---|---|---|
|2026-10-22，主实验phase5|100个有效性能作业及单项/组合Golden已审查；同期25W有球R4相对R0三轮配对Hz宏平均+6.928%|[正式阶段报告](REPORT.md)、[性能比较](PERFORMANCE_COMPARISON.md)、[正确性](CORRECTNESS_REPORT.md)；用户在该时点暂停后续，B5未完成|
|2026-10-22，后续接入|E01+A2+Graph已接入本地项目并同步/构建安装到机器人，源码/安装hash核验|[正常链路接入记录](integration/E01_a2_graph_20261022T103907Z/INTEGRATION_REPORT.md)；该次没有启动相机、生产感知或GPU benchmark，不能写成生产性能已验收|
|2026-10-23，运行捕获说明|核对每次加载后正式推理前捕获、正常帧Replay，补CPU/mock回归|[报告](integration/runtime_capture_20261023T013041Z/REPORT.md)；本次新增文档/测试未同步机器人，未做当天实机捕获验收|
|2026-10-23，MAXN预处理筛选|canvas/reuse正确性通过但性能门槛未通过，按停止条件结束|[负结果报告](preprocess_race/20261023T014627Z/REPORT.md)；不采用候选、不运行系统A/B，不用局部预处理倒数宣称Hz|

主实验同期R0/R4为14.580/15.590帧对每秒，属于25W、408MHz上限、Viser关闭的固定有球场景；不能与E03另一现场的16.812Hz或MAXN消息频率混比。R5额外C2增量不稳定，A1不保留；物理定位精度和长期稳定性未验收。[计时范围](PERFORMANCE_COMPARISON.md)

`CURRENT_PHASE.json`和`PAUSE_STATUS.json`保留主实验结束时的事实；后续安装事件由`integration/CURRENT_INTEGRATION.json`及对应报告记录。两者不能互相覆盖，也不意味着本页授权恢复测试。nano后续现场观察的证据缺口见[来源核对](../../docs/SOURCE_AUDIT.md#待补齐的证据)。

原始主run为本地产物引用：`runs/20261022T020842Z_78f1b7/`。阅读与复算入口：

- [CPU复算与证据](REPRODUCE.md)、[原始数据索引](RAW_DATA_INDEX.md)
- [测量基线](BASELINE.md)、[主实验隔离集成快照](INTEGRATION_REPORT.md)
- [历史暂停状态与待执行项](NEXT_RUN.md)、[计划](PLAN.md)、[接口边界](INTERFACES.md)

不因文档整理重做测量、安装候选或修改生产模型；新增测量须在独立run中记录对应环境和授权。
