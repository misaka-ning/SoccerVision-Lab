# E04 TensorRT 推理链路优化

当前状态（2026-10-22）：100个有效性能作业及单项/组合Golden已审查，本轮R4（A2+Graph）相对同期R0三轮配对Hz约+6.93%；R5额外C2收益不稳定。**用户已暂停后续实验**，不启动长稳、补测或生产部署。

- [正式阶段报告](REPORT.md)
- [全部性能比较与口径](PERFORMANCE_COMPARISON.md)
- [正确性与限制](CORRECTNESS_REPORT.md)
- [部署基线](BASELINE.md)、[集成与回滚](INTEGRATION_REPORT.md)
- [CPU复算与证据](REPRODUCE.md)、[原始数据索引](RAW_DATA_INDEX.md)
- [当前暂停状态](NEXT_RUN.md)、[计划](PLAN.md)、[接口边界](INTERFACES.md)

本轮有球同期R0/R4为14.580/15.590Hz，不与E03约16.812Hz的不同现场混比。候选未安装生产，B5长期稳定性和物理定位精度未验收，不能称E04全阶段完成。原始run为20261022T020842Z_78f1b7，CURRENT_PHASE.json指向已审查phase5，PAUSE_STATUS.json记录用户暂停。
