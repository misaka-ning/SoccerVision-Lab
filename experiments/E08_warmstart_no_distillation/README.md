# E08 / NoKD：WarmKD 的无蒸馏继续训练对照

E08 从 E07 使用的 **E05 best.pt** 开始，重新建立优化器，禁用蒸馏。它补齐 `E05 → 继续训练 → WarmKD` 的三方比较。当前完成实现、离线验收和 CPU 合成数据单步 smoke；真实 Train/Val 准备、CUDA smoke、正式训练及统一 Val 为 **not_run**。验证范围见 [VALIDATION.md](VALIDATION.md)。

## 为什么是 E08

审查基线 `7ab77739828b4e33b3342627fe293e892416d047` 的实验索引、E05/E06/E07 设计、实际入口和报告，以及远端分支/PR，未找到等价对照。E05 从官方单类 nano 初始化训练；E06 与 E05 同起点；E07 从 E05 best 开始且启用 KD。E02 的继续训练使用 E01-s，不能替代本对照。下一个未占用编号为 E08。

E06/E07 的报告确认它们已在 **2026-10-23** 完成训练及 Val；实验索引中的“待启动”已订正。这里不重新启动或覆盖历史 run。

## 固定实验设计

|项目|E07 WarmKD|E08 NoKD|
|---|---|---|
|初始化|E05 best.pt，第43轮|逐字节相同 SHA256|
|初始化 SHA|`a51bf6f3ec855e7cb126d097fe30e213d0588d37a9f1d2d9546f090b168dfd13`|相同|
|Train / Val|4346 / 1223；冻结图像、标注、metadata|相同成员与内容哈希|
|seed / 输入 / batch|42 / 640 / 8|相同|
|优化器|新 AdamW，lr0=0.001、lrf=0.01、weight_decay=0.0005|相同；不恢复 E05 optimizer|
|预算 / 早停|最多100轮，patience30，原生 fitness/best 选择|相同|
|增强、warmup、AMP、双头、NMS等|E07实际请求配置及有效默认值|除输出路径和KD开关外逐项比较|
|distill_model|E01-s 教师|**null**|
|dis|6.0|6.0（未构建KD时不参与损失）|

只将 `dis` 设为0仍可能加载教师，因此这里保留其值，唯一语义配置差异为 `distill_model=null`。运行时拦截原生 DistillationModel 构造及未声明的 checkpoint 加载，检查普通 nano 无教师/投影层，首步前所有状态张量与 E05 best 完全一致。导入库中的 KD 类定义不等于加载教师权重。

`prepare` 必须取得 E07 原 run 的 `train.yaml`、`train.effective.json`、`library_contract.json`、输入哈希和 `init.pt`；缺失即停止，不用模板冒充已核验的有效配置。模板仅供离线 dry-run 展示。允许通过参数定位迁移后的历史 run 和 `datasets/v1`，但模型、数据哈希和配置仍必须相同。默认 E07 run 为 `20261023T035555Z_s42_WarmKD_93e0cf`，E05 run 为 `20261023T023231Z_s42_90bcea`。

## 用户启动命令

在包含历史 run、冻结 Train/Val 的工作站仓库根目录运行。要求已有 Ultralytics8.4.173 / Torch2.9.1 环境；不安装或升级依赖。E05 原来的 `assets/yolo26n.pt` 必须存在且匹配 `PRETRAINED.json`，它仅用于原生 AMP 检查，不是学生或教师初始化。

```bash
E08=experiments/E08_warmstart_no_distillation
CPU=/opt/VisionStudio/runtime/bin/python
GPU=/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python

# 纯配置预览：不读取图片、不加载模型，也不产生训练结果。
"$CPU" "$E08/e08.py" dry-run

# 完整准备：只读取冻结Train/Val，独占新建run，记录来源和源码快照。
"$CPU" "$E08/e08.py" prepare
RUN=$("$CPU" -c 'import json,sys; print(json.load(open(sys.argv[1]))["run"])' "$E08/LOCAL_READY.json")
"$CPU" "$E08/e08.py" dry-run --run "$RUN"

# 用户手动运行：真实batch8/640，最多8次AMP尝试，实际更新一次即结束。
"$GPU" "$E08/e08.py" smoke --run "$RUN"

# 用户确认空闲GPU后手动运行长训练；前台输出，可在自己的tmux会话中启动。
bash "$E08/start_training.sh" "$RUN"
bash "$E08/status.sh" "$RUN"

# 训练后统一比较；首次对E05/E08/E07均采用同一个存档评估器做完整Val。
"$GPU" "$E08/e08.py" compare --run "$RUN" --evaluate --device 0
# 后续只核验、重算已有逐图结果并汇总，不启动预测。
"$GPU" "$E08/e08.py" compare --run "$RUN" --device 0
```

迁移目录时 `prepare` 可追加 `--e07-run /path/to/E07/run --e05-run /path/to/E05/run --data-root /path/to/datasets/v1`；必要时 `--init /path/to/E05_best.pt`，仍强制匹配 E07 的 init SHA。仅有仓库发布权重而缺少历史 run 时，无法证明完整配置/数据身份，不能通过正式 prepare。

无已准备 run 时运行 `compare` 可生成全 `not_run` 的 JSON/CSV/Markdown 框架。`compare --evaluate` 是显式耗时入口，不会自动由 prepare/smoke/train 触发；失败目录保留，后续仅复用通过完整性校验的结果。设备不同分别评估，阈值固定0.45，避免工作点混用。

E05/E06/E07/E08 共用 E05 GPU 互斥锁；发现其他计算进程则退出，不排队或结束其他进程。run、smoke、正式 train、比较目录各自隔离；不生成 train2，不覆盖已有初始化/权重/results.csv。E08暂不提供自动恢复入口：失败 run 保留，排查后新 prepare；`resume-last.pt`仅作为原始诊断证据保存，不可将新优化器对照偷偷切成 E05 resume。

## 比较与预算口径

统一比较保存后的 best.pt：AP50、AP50–95、整体 Precision/Recall、Small Recall、Occluded Recall、无球图片误报率。完整 Val1223图/855GT/410无球图；640、FP32、one-to-many+外部 NMS、离线batch4、min_conf=0.001、NMS IoU=0.7、max_det300。固定工作点 conf=0.45，匹配 IoU=0.5。AP沿用共享Ultralytics算法，不从训练器CSV或历史报告抄数值。

Small/Occluded来自冻结metadata场景标记，以场景GT框数为召回分母；场景可重叠。无球FPR为“至少一个过阈值预测的无球图数/无球图数”，同时输出分子分母，不使用FP框数/总图片数替代。

E07历史评估遇到有限、非反向的零面积候选。本入口在新run中存档共享评估器并明确应用同一项准入修复：只把非法框检查的 `<=` 改为 `<`，保留零面积候选并按IoU=0参与原共享指标；没有过滤候选。保存原/有效源码SHA和diff，三模型统一使用该副本。共享指标、NMS及冻结历史源码均不改写。第一次统一比较重新评估三模型，避免混入 E07 历史私有修订及不同代码哈希的结果；以后可核验复用本入口生成的完成结果。

每次汇总核验完成标记、完整Val成员/顺序、配置/权重/源码/metadata哈希、FP32分支、GT与场景内容，并用共享指标重算逐图预测。汇总输出 JSON/CSV/Markdown，缺失模型、指标、原始证据或预算字段保留 `not_run`。原始完整结果缺失不等于否认历史训练；本PR不把报告中四舍五入的数值伪装为新实测。

预算分别记录：最大轮数、patience、CSV实际轮数、最佳CSV轮次、原生stopper最佳轮次、停止原因及证据、耗时、batch数、optimizer尝试/真正更新次数。训练器最终验证回调不增加CSV轮数。旧E05/E07没有实际更新计数时保持not_run；旧停止原因从CSV推断并注明四舍五入局限，不猜测更新次数。输出 E07−E08 的轮数/耗时/更新差，以及各指标百分点差。

E05前置训练完整耗费73轮，初始化best只经历43轮；两条继续训练路线都承担这部分来源成本。E08−E05用于衡量额外训练，E07−E08用于观察同起点/配方/停止规则下KD的收益与误报代价。早停造成的实际预算差异须一起报告，不能宣称固定步数因果效果、单seed显著性或新的部署速度。结果有负收益也保留。

不读取Test图片/标注，不进行机器人、Engine、阈值或生产配置变更。
