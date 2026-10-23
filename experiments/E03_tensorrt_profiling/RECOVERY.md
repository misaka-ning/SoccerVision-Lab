# E03 回收记录（已完成）

**2026-10-21 已恢复连接并完成回收。** `result_bundle.tar.gz` 为 264248794 字节，远端/本机 SHA256 一致；解压后 625 个清单文件的大小与 SHA256 全部匹配。已在本机 CPU 重算逐层、正常计时与 Nsight，补齐 [REPORT.md](REPORT.md) 和 [结果索引](results/README.md)。重启后没有重建或重测。

归档 SHA256：`7ec6706e503327a44006951a78c9684402dd98c2bc7960654a0a957a6c5b004f`。归档与文件验证完成时间为 `2026-10-21T10:19:06Z`。

以下保留断线期间的恢复说明作为历史记录。当时机器人电量耗尽关机，SSH 返回 `No route to host`，邻居项为 FAILED；当前不再阻塞。

## 已经完成，不要重新运行

- 原有 Engine 三轮；四份新 Engine 构建；64 张 Val 的四项一致性检查。
- 新 performance 三轮与 detailed 单轮正常校核；新 detailed 和原有 Engine 各三次逐层 profile。
- E01 trtexec 常驻/传输/Graph 诊断；有效 Nsight 冒烟、Engine、检测器和 Graph 重采。
- 单轮 30 秒 E01 完整系统锚点；原生产文件 12 项终检不变。
- 本实验监控 PID 10427/10939 已停止，采集控制器已退出，测试端口已关闭。不要在重连后按这些旧 PID 杀进程，PID 可能已复用。

原始文件路径：

```text
/home/nvidia/soccer_backend_tensorrt/results/E03_tensorrt_profiling/20261021T080741Z_824b47
```

本机已有 A 阶段和历史系统原始计时、固定输入与摘要：

```text
/home/misaka/workspace/experiments/E03_tensorrt_profiling/runs/20261021T080741Z_824b47
```

## 恢复顺序（已执行）

1. SSH 连接既定地址，先只读检查目录和文件存在。密码仍只在交互式提示中输入，不写入脚本或配置。
2. 先回收小文件：`analysis/`、`profiles/`、`profiles_legacy/`、`correctness/summary.json`、`production_artifact_integrity.json`、`run_record.json`，优先拿到完整 Top20 与 L19 明细。
3. 确认原采集任务已结束后，在本 run 内打包完整文件；排除归档文件自身和先前回收包。已有归档时先检查，避免覆盖。保存远端包的 SHA256 与大小。
4. 复制至本机该 run，核对 SHA256。先检查 tar 成员，拒绝绝对路径、`..` 越界或越界链接；只解压到该实验自己的 run，不覆盖其他项目文件。
5. 本机 CPU 分析，不在机器人重测：

```bash
/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python \
  /home/misaka/workspace/experiments/E03_tensorrt_profiling/analyze.py \
  --run /home/misaka/workspace/experiments/E03_tensorrt_profiling/runs/20261021T080741Z_824b47
```

6. 比对完整原始分析与 `MEASUREMENT_SUMMARY.json` 的 readback 数字；补齐新组 n/P99、Graph trace 的活动/间隔以及 detector 方法区间的重叠分析。检查每组 profile 为三次，互斥模块比例合计 100%。
7. 发布新 detailed Engine 的 E01/E02 Top20 CSV（实际输入输出 shape、dtype/format、tactic），另发布原有 Engine 的 Top20 时间表。旧 Engine 的内部 metadata 不可得，不从新图代填。
8. 检查 L19 的实际内部 shape/format/tactic 和额外 Copy，保留无法证明的具体因果。排除首个节点不完整的 `legacy_graph` 作为主要 trace，使用 `legacy_graph2`；保留首次失败文件。
9. 完善 `REPORT.md`，将摘要来源改为已回收并校验；更新交付状态和运行记录。仅在全部交付完成后标记最终验收完成。

当前本机 `analyze.py` 比远端脚本多了 detector NVTX 方法区间与 GPU/API 的重叠分解。恢复后使用本机最新版即可处理已有 SQLite，无需新增采集。不要把首次本机只收到旧计时所生成的空 `profile_summary.json` 当作远端没有 profile。

本次没有自动调整时钟、升级依赖或部署新模型。用户没有要求 commit/push，后续回收也不自动提交。

最终已核对断线摘要 118 项数值、四组各三次 profile、互斥占比合计 100%、四项正确性与新 detailed Top20 的完整 I/O/tactic 覆盖。首次 Graph trace 质量失败记录保留，主要结论使用 legacy_graph2。原始归档不改写；最终交付另追加 final_delivery.json。

最终报告与结果已在本机完成后，尝试将报告副本回传机器人时再次收到 No route to host；该可选备份未成功。完整原始归档、全部校验文件和最终报告已在本机保存，此项不构成本次交付的缺项，也无需再连接机器人才能复现分析。
