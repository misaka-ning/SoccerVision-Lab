> 历史执行说明：本轮单项正确性已完成并验收，不再启动。当前命令见 [NEXT_RUN.md](NEXT_RUN.md)。

# E04 下一步：单项实机正确性

E04-0 已验收，候选代码已审查并通过65项CPU集成回归、9项工具测试；实机正确性和性能尚未通过。

本次脚本已上传并通过机器人 dry-run，冻结包与源码/配置/模型 hash 检查通过，不修改生产项目。不要再运行已完成的 stage0。

## 用户启动

在 `nvidia@192.168.98.235` 的 SSH 终端执行一条命令：

```bash
bash /home/nvidia/soccer_backend_tensorrt/results/E04_tensorrt_pipeline/20261022T020842Z_78f1b7/phase1_20261022T031913Z_260f0c/scripts/start_correctness.sh
```

预计约5～8分钟（估计值，取决于初始化和压缩速度），可以退出 SSH，无需持续观察。启动器输出独立日志路径与PID，重复运行不会覆盖旧 console；内层全局GPU锁保证没有并行采集。机器人应处于可供GPU测试的安全窗口，不同时启动其他感知/benchmark。

完成后回复“E04 单项正确性跑完了”，协调 Agent 回收并审查。若失败，不删除历史；查看独立日志原因，再由协调 Agent 判断是否显式 `--resume`。不必为查看进度重启任务。

## 实际执行

1. B1/B2：同一E01 Engine，10次固定输入及61组变化的真实预处理输入，Graph与当前原路径、冻结输出逐元素比较；检查每次更新输入、前次输出归属、模拟NMS改写、capture/replay/update计数与restore。
2. 独立重放 R0、A1、A2、A1+A2、Graph、C1探针、C2，每个100次预热后回放61对Val。使用冻结相机内参和确定性时间戳，不打开ZED、不发布ROS。
3. 严格对比预处理、原始输出和最终框张量，以及候选数量/类型/顺序、双目选择、3D测量、跟踪与七字段ROS。Engine、有效配置、内参、实际effective、fallback和恢复状态都要检查。
4. Graph失败时保留证据并跳过Graph检测器重放，继续其他独立方案；重复R0失败则停止其余候选，先查参考或环境差异。

A3因现有NMS ABI不兼容且无已验证替代而标记不可用。C1仅作八段方法墙钟诊断，GPU Resize、异步和双缓冲本轮首个候选未实施。A+B/A+B+C尚不组合。

`CORRECTNESS_COLLECTION_COMPLETE.json` 只表示这些采集和自动检查完成，仍待协调审查；`CORRECTNESS_COLLECTION_FINISHED.json` 表示存在失败。未运行正式三轮候选测速与B5长期稳定性，不产生加速或上线结论。

包 SHA256：`f196660b259d0fb688ecf946663e15f358f3feaf793d32eb8c03aea1a5290be5`；manifest SHA256：`16d34236f9cf8f6ad7206afe6ad7b263102d6222b20a17506ae85e2f77d9ab43`；隔离集成提交 `e0672063ed58446a9ed3ecec59ad854380f5795b`。原stage0脚本、原模型、生产源码和配置不覆盖。
