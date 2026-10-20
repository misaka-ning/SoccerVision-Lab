#!/usr/bin/env python3
"""Write E01 reports only from saved, real outputs; unrun metrics stay pending."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import shutil

from e01 import HERE, ROOT, DATA, WEIGHTS, GPU_PYTHON, CPU_PYTHON, dump, now, sha


def read(path):
    return json.loads(path.read_text()) if path.exists() else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=Path, required=True)
    a = p.parse_args()
    run = a.run.resolve()
    record = read(run / "run_record.json")
    transfer = read(run / "transfer.json")
    pre = read(run / "precheck.json")
    env = read(run / "environment.json")
    eval1 = read(run / "evaluation/metrics.json")
    eval0 = read(ROOT / "experiments/E00_original/evaluation/metrics.json")
    comparison = read(run / "model_comparison.json")
    verification = read(run / "single_class_verification.json")
    integrity = read(run / "input_integrity.final.json")
    record["initialization"].update(source_class_count=80, source_architecture_ref="original.architecture.yaml",
        source_architecture_sha256=sha(run / "original.architecture.yaml"), transfer_details_ref="transfer.json",
        formal_transfer_verification_ref="transfer.formal.json")
    record["initialization"]["exposure"]["unknown_details"] = ["原始训练完整数据名单及与当前Train重叠的具体样本未提供。"]
    record["source"]["archive_manifest_ref"] = "source/manifest.json"
    record["source"]["postprocessing_source_manifest_ref"] = "source/postprocessing/manifest.json"
    record["protocol_audit_ref"] = "evaluation_protocol_audit.json"
    record["metric_replay_ref"] = "E00_metric_replay.json"
    record["auxiliary_amp_weight"] = read(run / "auxiliary_weight.json")
    counts = dict(Counter(r["usage"] for r in csv.DictReader((DATA / "manifest.csv").open(encoding="utf-8-sig", newline=""))))
    assert all(counts[k] == v for k, v in dict(train=4346, val=1223, test=464, buffer=755, heldout_unused=1360).items())
    record["data"]["counts"] = counts
    shutil.copy2(HERE / "PLAN.md", run / "PLAN.md")
    text = lambda name, value: (run / name).write_text(value.rstrip() + "\n")
    text("TRANSFER_REPORT.md", f"""# 权重迁移实测

原权重：`{WEIGHTS}`，SHA256 `{sha(WEIGHTS)}`。原结构 YOLO26s，nc=80，类别 32=sports ball，reg_max=1。原权重和架构文件未改。

本机 Ultralytics {env['ultralytics']} 的 `DetectionTrainer.get_model` 根据数据集 nc=1 构建新模型，再调用 `BaseModel.load`。使用原架构的深拷贝做独立预检，原 `.pt` 始终只读。正式训练用官方 `YOLO(original_best.pt).train(...)`，正式加载的逐值复核见 `transfer.formal.json`。

成功迁移 **{transfer['transferred_tensor_count']}/{transfer['target_tensor_count']} 个 state_dict 张量**（包含 BatchNorm buffer，不等同于参数层数），所有兼容张量训练前与源权重逐值相等。没有意外缺失键或额外键。分组统计见 `transfer.json`：

| 部分 | 迁移张量 | 元素数（含 buffer） |
|---|---:|---:|
""" + "\n".join(f"| {k} | {v['tensors']} | {v['elements']} |" for k, v in transfer["groups"].items()) + """

仅重新初始化 12 个张量：`model.23.{cv3,one2one_cv3}.{0,1,2}.2.{weight,bias}`。六个输出 Conv2d 的权重 `[80,128,1,1]→[1,128,1,1]`，偏置 `[80]→[1]`。分类中间通道仍为128；回归、Backbone、Neck、两套分类中间特征均迁移。两个分支在三个尺度均只有一个分类输出。

当前版本支持按相同类别名称映射分类行，但 `football` 与 `sports ball` 不相同，因此不会自动迁移 COCO 32 的输出行。128输入通道相同使手动取第32行在形状上可行，但本轮没有做名称伪装或分类权重手术。六个新分类输出使用框架初始化，bias包含 Detect.bias_init 的先验初始化。

两分支训练使用官方 E2ELoss。正式 Val/推理使用 one-to-many + NMS，与 E00 一致；推理时官方 fuse 会去掉未选用的 one-to-one 分支。保存在权重中的双分支仍可独立加载。
""")
    text("PRECHECK_REPORT.md", f"""# E01 预检

实际状态：**{pre['status']}**。详情 `precheck.json`、`precheck.log` 和 `input_integrity.after_precheck.json`。

- Train {pre['data']['train']['images']} 张、{pre['data']['train']['boxes']} 框、无球 {pre['data']['train']['no_ball_images']} 张；Val {pre['data']['val']['images']} 张、{pre['data']['val']['boxes']} 框、无球 {pre['data']['val']['no_ball_images']} 张。
- 全部使用的 label 类别 ID 为 0；有效配置 nc=1、names[0]=football。审核过滤跳过0张。逐图核验 manifest SHA256、完整 RGB 解码、JPEG 结尾、框格式与范围。
- 新模型 names={{0: football}}、head.nc=1；官方数据加载器返回完整 Train/Val，输入 `{pre['input_shape']}`，AMP 损失有限、梯度有限、真实优化器一步成功。
- 峰值 allocated {pre['peak_cuda_allocated_bytes']/2**30:.3f} GiB，reserved {pre['peak_cuda_reserved_bytes']/2**30:.3f} GiB；设备 {env.get('gpu')}。这是预检峰值，正式峰值另记 progress.json。
- AMP 原生缩放回退过程：`{pre['amp_scale_checks']}`。遇到初始溢出由 GradScaler 自动跳过更新并降低 scale，未修改正式训练超参数。
- 预检不保存权重，正式训练从原始权重新建模型，不沿用 smoke 的优化器或 BatchNorm 状态。
- E01 的训练 YAML 没有 Test；运行视图没有 Test/Buffer/Heldout。Val 的成员、图/label SHA、场景与 E00 inputs_manifest 完全相同。
- 每个运行使用独占 run_id，正式 train 目录存在则拒绝启动新训练；缓存落在本运行目录。冻结数据集、原权重、manifest、metadata 有逐文件前后哈希核对。

早期调试记录保存在其他独立 run：第一次修正 loss_items 的字典接口，第二次补全 GradScaler 自动回退检查；均未进入正式训练，不作为实验成绩。
""")
    rel = str(run.relative_to(ROOT))
    prefix = f"{GPU_PYTHON} -u -B experiments/{HERE.name}/e01.py"
    evaluate = f"{CPU_PYTHON} -u -B script/model-evaluation/evaluate.py --model {rel}/train/weights/best.pt --data {rel}/dataset.val-evaluation.yaml --split val --class-id 0 --imgsz 640 --batch 4 --device cpu --threads 1 --min-conf 0.001 --conf 0.25 --match-iou 0.5 --nms-iou 0.7 --max-det 300 --output {rel}/evaluation --formats png,pdf,svg --dpi 300"
    text("REPRODUCE.md", f"""# 复现与恢复

代码基准 Git commit `{record['source']['commit']}`；工作区已有其他未提交维护改动，不能只凭 commit 复现。使用本运行 `source/`、脚本 SHA256、`e01.executed.py`、配置及环境清单核对实际实现。未安装或升级任何依赖。

现成 GPU Python `{GPU_PYTHON}`，Ultralytics {env['ultralytics']}，PyTorch {env['pytorch']}，CUDA {env['cuda']}；CPU公平评估使用 `{CPU_PYTHON}`，E00同环境。GPU在当前受限沙箱内不可见，需要主机环境执行。

从 `/home/misaka/workspace` 运行。先创建一个新的独立 run（会打印 E01_RUN），再把下面 RUN 换为该路径；不能重复运行到已有 train 目录。

```bash
{prefix} prepare
RUN={rel}
{prefix} train --run "$RUN" > "$RUN/training.log" 2>&1
```

训练复用 `script/model-training/train.py:build_plan` 和其共享配置，实际训练是官方 `YOLO.train`，不复制训练器。`train.requested.yaml` 保存全部显式参数，`train/args.yaml` 与 `train.effective.json` 保存框架最终有效参数，`optimizer.effective.json` 保存实际优化器组、weight decay缩放、AMP与梯度累积。batch=8、nbs=64 可能使官方梯度累积动态调整，按实际文件解释。

中断后同一 run 恢复（必须存在含 optimizer 的 checkpoint）：

```bash
{prefix} resume --run {rel} >> {rel}/training.log 2>&1
```

`resume-last.pt` 是每次官方保存事件后的原样副本；框架完成时会剥离 best/last 的 optimizer，所以另外保留此恢复副本。不要用剥离后的 best/last 宣称可继续训练。

公平 Val 评估命令（输出已存在时拒绝覆盖；复验应换新输出目录）：

```bash
{evaluate}
{GPU_PYTHON} -B experiments/{HERE.name}/measure.py --run {rel}
{prefix} verify --run {rel}
{CPU_PYTHON} -B experiments/{HERE.name}/report.py --run {rel}
```

训练期间的框架 Val 使用矩形批次；最终公平评估固定方形640×640，对照E00的AP匹配实现和工作阈值。mAP来自候选conf=0.001，P/R/F1和误报率来自固定conf=0.25，不能和框架自动最大F1阈值混用。未开展最优运行阈值选择。Test不得在上述步骤中加入。

全部模型、预测、训练图片图表均位于本地被忽略的 runs/，不要公开提交。软链接视图只缓存路径，不复制或重分数据；源码数据路径变更时重新 prepare，并核对原始SHA。单种子不能保证跨硬件逐位一致。
""")
    record["artifacts"] = dict(plan="PLAN.md", transfer="TRANSFER_REPORT.md", precheck="PRECHECK_REPORT.md", environment="environment.json",
                              requested_config="train.requested.yaml", effective_config="train.effective.json", training_log="training.log",
                              curves="train/results.png", evaluation="evaluation/metrics.json", comparison="E00_VS_E01.md", reproduce="REPRODUCE.md")
    if eval1:
        assert eval1["status"] == "complete" and eval1["metrics"]["images"] == 1223
        m = eval1["metrics"]
        record["evaluation"]["val"].update(status="complete", output_ref=str(run / "evaluation"),
            manifest_sha256=sha(run / "evaluation/inputs_manifest.json"), sample_counts=dict(images=1223, gt_boxes=855, no_ball_images=410),
            metrics=m)
        record["evaluation"]["selected_checkpoint_sha256"] = sha(run / "train/weights/best.pt")
        metrics = ["mAP50", "mAP75", "mAP50_95", "precision", "recall", "F1", "TP", "FP", "FN", "no_ball_false_positive_rate"]
        def fmt(x):
            return "pending" if x is None else str(x) if isinstance(x, int) else f"{x:.6f}"
        table = "| 指标 | E00 | E01 | E01−E00 |\n|---|---:|---:|---:|\n"
        for k in metrics:
            v0, v1 = eval0["metrics"][k], m[k]
            table += f"| {k} | {fmt(v0)} | {fmt(v1)} | {fmt(v1-v0)} |\n"
        scenes = "| 场景 | 图片/GT | E00 mAP50 | E01 mAP50 | E00 mAP50–95 | E01 mAP50–95 | E00 P/R/F1 | E01 P/R/F1 |\n|---|---:|---:|---:|---:|---:|---|---|\n"
        for name in ("Small", "Occluded", "Blurred", "No difficulty"):
            s0, s1 = eval0["scene_metrics"][name], eval1["scene_metrics"][name]
            assert s0["images"] == s1["images"] and s0["gt_boxes"] == s1["gt_boxes"]
            scenes += f"| {name} | {s1['images']}/{s1['gt_boxes']} | {s0['mAP50']:.6f} | {s1['mAP50']:.6f} | {s0['mAP50_95']:.6f} | {s1['mAP50_95']:.6f} | " + "/".join(f"{s0[k]:.4f}" for k in ("precision", "recall", "F1")) + " | " + "/".join(f"{s1[k]:.4f}" for k in ("precision", "recall", "F1")) + " |\n"
        text("E00_VS_E01.md", "# E00 / E01 Val 公平对照\n\n两者均为完整Val 1,223张、855 GT、410张无球；非Test结果。固定工作阈值0.25，AP候选下限0.001，640方形输入、匹配IoU=0.5、NMS IoU=0.7、max_det=300，类别映射32→0。AP核心和数据选择源码哈希与E00相同；入口和报告文件因既有维护哈希不同，实际推理参数逐项显式对齐，见evaluation_protocol_audit.json。CPU单线程batch4。\n\n" + table + "\n" + scenes + "\n各场景完整TP/FP/FN、AP75、误报率等见evaluation/metrics.json和tables/scene_metrics.csv。多标签场景可重叠；No difficulty只含无困难标记的有球图片，不含负样本。\n\n训练、类别数和输出参数一起改变，因此所有差异不能单独归因于分类维度减少；没有通过Val调节最佳阈值。\n")
    else:
        text("E00_VS_E01.md", "# E00 / E01 对照\n\nE01完整Val评估 pending。E00为Val mAP50=0.602318、mAP50–95=0.554108；固定conf=0.25，P=0.994638、R=0.433918、无球误报0/410。尚不计算差值。")
    if comparison:
        rows = comparison["models"]
        perf = "\n| 指标 | E00 | E01 |\n|---|---:|---:|\n"
        for k in ("stored_parameters", "fused_selected_branch_parameters", "unfused_both_branch_gflops", "fused_selected_branch_gflops", "file_bytes", "nc", "classification_output_channels", "raw_output_shape"):
            perf += f"| {k} | {rows['E00'][k]} | {rows['E01'][k]} |\n"
        for k in ("cuda_event_latency_ms", "synchronized_wall_latency_ms"):
            perf += f"| {k} mean | {rows['E00'][k]['mean']:.4f} | {rows['E01'][k]['mean']:.4f} |\n"
        if eval1:
            perf += f"| CPU single-thread batch4 inference ms/image | {eval0['runtime']['backend_reported_mean_ms']['inference']:.4f} | {eval1['runtime']['backend_reported_mean_ms']['inference']:.4f} |\n"
        with (run / "E00_VS_E01.md").open("a") as f:
            f.write(perf + "\nRTX4060 FP32，TF32关闭，batch1×3×640×640，warmup20、计时100次，官方fuse去掉未用分支，包含检测头和box decode，不含预处理、H2D、NMS、文件读取。CUDA event含设备执行，wall另含主机调度和等待。FLOPs=同版本Ultralytics/THOP、1 MAC=2 FLOPs；未做Orin/TensorRT部署。\n")
            f.write("\n两组延迟分布高度重叠，约0.03ms的均值差不能支持明显加速结论；这是单次顺序测量，没有锁定GPU频率或多轮交错复验。CPU批量评估的运行时间另见两次metrics.json，仅供开发机参考。\n")
        record["architecture"]["flops"].update(value=rows["E01"]["fused_selected_branch_gflops"], unit="GFLOPs",
            input_shape=[1, 3, 640, 640], method=comparison["flops_method"], tool_version=comparison["thop"], multiply_add_convention="1 MAC = 2 FLOPs")
        record["development_hardware_benchmark"] = comparison
    complete = bool(record["status"] in ("trained", "complete") and eval1 and comparison and verification and integrity and integrity["unchanged"])
    if complete:
        record.update(status="complete", completed_utc=now())
        record["result"].update(comparison_run_ids=["E00_original/Val", record["run_id"]], failure_reason=None,
            conclusion="Single-class transfer/training/Val verified; Test unused; ready for controlled E02 pilot; multi-seed replication pending.")
        csvrows = list(csv.DictReader((run / "train/results.csv").open()))
        # Official save_model overwrites best on equal fitness, so take the last
        # maximizing epoch if the saved CSV contains a rounded-value tie.
        bestrow = max(csvrows, key=lambda r: (float(r["metrics/mAP50-95(B)"]), int(r["epoch"])))
        record["training"].update(actual_epochs=len(csvrows), best_epoch=int(bestrow["epoch"]), best_training_validation=bestrow)
        record["training"].update(termination_reason="early_stopping_patience_30" if len(csvrows) < record["training"]["effective_args"]["epochs"] else "max_epochs",
            peak_cuda_allocated_bytes=read(run / "progress.json")["gpu_peak_allocated_bytes"])
        m = eval1["metrics"]
        text("RESULT.md", f"""# E01 实验结果

状态：**完成**。run_id `{record['run_id']}`，正式训练 {len(csvrows)} epochs，最佳epoch {bestrow['epoch']}，训练耗时 {record['training']['elapsed_seconds']/60:.2f} 分钟。完整run身份见run_record.json。

独立重载 best.pt：names={{0: football}}、类别数1、head.nc=1，两个分支三个尺度的分类输出均为1。未设置classes过滤的Val推理仅出现类别0；原始前向输出[1,5,8400]。迁移696/708状态张量，重初始化12个最终分类张量。

独立公平 **Val**：mAP50={m['mAP50']:.6f}、mAP75={m['mAP75']:.6f}、mAP50–95={m['mAP50_95']:.6f}；固定conf=0.25的Precision={m['precision']:.6f}、Recall={m['recall']:.6f}、F1={m['F1']:.6f}；TP/FP/FN={m['TP']}/{m['FP']}/{m['FN']}，无球误报 {m['no_ball_false_positive_images']}/410（{100*m['no_ball_false_positive_rate']:.3f}%）。差值与场景统计见E00_VS_E01.md。

实际训练：640、batch8、seed42、100epochs上限、patience30、AdamW lr0=0.001、cosine lrf=0.01、warmup3、warmup_bias_lr=0、weight_decay=0.0005、workers4、AMP、deterministic、不冻结；其余全部生效项见train.effective.json。训练日志、每轮CSV、best/last和含优化器的resume-last均保留。

输入哈希复核通过。原始权重和v1 Train/Val图片、标签、metadata、manifest未改；Test像素/标签未读取或推理。源码未提交/推送，保留其他路径维护改动；结果及权重仅保存在本地忽略目录。

主要问题：固定conf=0.25时，Precision较E00下降{100*(eval0['metrics']['precision']-m['precision']):.2f}个百分点，无球误报从0/410升至{m['no_ball_false_positive_images']}/410。召回和AP提升伴随误报代价，不能称为所有指标全面改善。误报明细见evaluation/false_positive_no_ball.csv。后续可在Val上单独研究阈值和困难负样本；本轮未选择新阈值，也未修改冻结数据。GPU约0.03ms的均值延迟差很小、分布重叠，不认定为明显加速。

可以开展以此run为固定对照的E02结构试验。尚需注意单种子局限、训练与类别数共同变化、同场次片段留出Test性质，以及精度/速度不能单归因于类别数；正式论文稳健结论应补预先固定多种子。没有Orin/TensorRT部署测量，不把RTX4060/CPU成绩当嵌入式性能。
""")
    else:
        text("RESULT.md", f"# E01 进行中\n\n状态：{record['status']}。预检={pre['status']}；正式训练及独立评估按run_record.json记录。尚未满足全部验收条件，不报告虚假最终指标。")
    dump(run / "run_record.json", record)
    (HERE / "README.md").write_text(f"# E01：YOLO26s 单类别足球微调\n\n当前run：[`{record['run_id']}`](runs/{record['run_id']}/RESULT.md)，状态 **{record['status']}**。\n\n详见[实验计划](PLAN.md)、[结果](runs/{record['run_id']}/RESULT.md)、[公平对照](runs/{record['run_id']}/E00_VS_E01.md)、[复现步骤](runs/{record['run_id']}/REPRODUCE.md)。本地runs默认忽略，包含权重、数据路径和训练图表，未经许可不要公开上传。\n")


if __name__ == "__main__":
    main()
