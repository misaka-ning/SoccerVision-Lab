# E06 / KD1 训练与独立 Val 报告

2026-10-23；run：`20261023T034325Z_s42_KD1_f1347d`。**正式训练及完整独立 Val 已完成，产物待用户验收。** 未导出或部署模型。

## 正式训练与评估结果

RTX4060 上完成44轮，第14轮最佳，连续30轮未改善后正常早停，编排耗时32.33分钟。`best.pt` SHA256：`6f8719c825c39daa7fb283246de0005b468d01034525d8d3f9c187bc021a73d0`。教师参数及BN统计保持不变，评估后11,175项冻结输入hash重验通过。

本次使用保存后的最佳模型，完整开发Val1223张、855个GT框、410张无球图，跳过0张；640、FP32、one-to-many+外部NMS、NMS IoU=0.7、max_det=300。离线评估batch4；P/R使用conf=0.45及匹配IoU=0.5，AP保留分数≥0.001的候选。没有访问冻结Test。

|模型|mAP50|mAP50–95|Precision|Recall|无球误报图片|
|---|---:|---:|---:|---:|---:|
|E01-s|96.017%|78.567%|97.100%|90.058%|12/410，2.927%|
|E05-n|94.165%|76.846%|98.907%|84.678%|4/410，0.976%|
|E06-KD1|96.506%|77.192%|94.272%|92.398%|25/410，6.098%|

E06固定工作点TP790、FP48、FN65。Small/Occluded/Blurred Recall分别为92.340%/82.288%/90.179%，相对E05提高12.553/12.177/9.375个百分点。整体Recall提高7.719个百分点，mAP50–95提高0.346个百分点，但Precision下降4.635个百分点，无球误报4→25张。召回恢复明显，同时存在明确的误报代价，不是全面改善。

E06与E05同初始化、同配方，E06增加教师及蒸馏；实际早停轮数不同，且只有单seed。这里的mAP来自独立评估，不能与训练器最佳轮CSV的77.170%混用。未做Jetson性能、双目定位或系统A/B，不提供机器人Hz结论。

本轮由E07统一入口串行评估两模型，E06原始输出保存在E07运行归档中，E06本run的`validation_result.json`记录指向及hash。E01/E05复用通过来源核验的既有完整结果；E06只执行了一次完整Val。

- [四模型完整对照、误报取舍及复现方法](/home/misaka/workspace/experiments/E07_warmstart_distillation/runs/20261023T035555Z_s42_WarmKD_93e0cf/val_0p45_20261023T061225Z_e643a0/COMPARISON.md)
- [E06逐图评估报告](/home/misaka/workspace/experiments/E07_warmstart_distillation/runs/20261023T035555Z_s42_WarmKD_93e0cf/val_0p45_20261023T061225Z_e643a0/E06_KD1/REPORT.md)

以下保留准备阶段的配置和短时验证记录。

## 本轮配置

冻结E01-s作为教师，学生使用与E05完全相同的FP32初始化，原生Ultralytics8.4.173特征蒸馏，`dis=6.0`。保持E05的640、batch8、seed42、AdamW、AMP、最多100轮、patience30及全部增强配置。教师、初始化和未蒸馏对照的SHA见README及run记录。

E05完整独立Val已回收并核验：mAP50-95 76.846% vs E01 78.567%，整体Recall 84.678% vs 90.058%；Small/Occluded Recall损失分别约6.38/9.96个百分点。E05无球误报更少（4/410 vs 12/410）。这些是E06设计依据，不是E06结果。

## 实际验证

|项目|结果|
|---|---|
|冻结输入|11,175项hash核验通过，包含全部Train/Val图片及标注；未打开Test图片/标注|
|学生起点|E06 `init.pt`与E05初始化SHA完全一致；正式首步前还有逐张量检查|
|原生KD接入|实际进入DistillationModel；教师/学生特征层为16、19、22，23层head仅用于权重生成|
|真实Train batch|8张，640×640，包含13个增强后GT框；只在smoke副本更新|
|实际优化器更新|1次；正式初始化、E01/E05模型未变化|
|学生梯度|366个梯度张量，成功更新时全部有限、非零|
|投影层梯度|12个梯度张量，成功更新时全部有限、非零；训练专用参数517,888|
|教师冻结|无梯度、无Adam状态；参数及BN统计量哈希前后完全相同|
|保存/续训|原生checkpoint保存后重建教师、精确恢复投影层及optimizer，恢复起始epoch为零起点1|
|移除蒸馏包装|普通nano参数2,504,190（未融合、含双训练头）；没有教师/投影层，学生权重逐值保持|
|独立学生推理|CPU FP32 batch2输出`[2,5,8400]`，数值有限|
|更新阶段显存|Torch peak allocated 1,419,589,632字节（约1.32GiB），reserved 1,528,823,808字节；不是全设备显存，也不代表完整训练长期峰值|
|环境|RTX4060，Torch2.9.1+cu128、CUDA12.8；Ultralytics源码hash在CPU/GPU环境核对一致|
|工程检查|8项单元测试通过；包括冻结配置/模型/数据、E05/E06互斥、原生加权L2与AMP溢出辨别；Python及Shell语法通过|

原生AMP的初始scale=65536产生非有限缩放梯度，前4次尝试由GradScaler跳过，scale依次降低到4096；第5次全部梯度有限，实际完成一次参数更新。没有降低batch、关闭AMP、调整dis或修改训练库。smoke计数明确区分尝试与实际更新，临时模型不作为正式候选。

首个准备run `20261023T033939Z_s42_KD1_da2fa7` 的检查把AMP初始溢出视作无效梯度，提前退出，未到optimizer更新；保留其源码、配置、日志及`smoke_failed`状态。随后修正的是短时验证逻辑，另建当前run，并追加2项回归测试；原失败记录未覆盖。

## 原始证据与待执行项

当前run内：`run_record.json`、`preflight.json`、`smoke_console.log`、`smoke/train/`、`smoke/student_only.pt`、`protected_inputs.json`、`library_contract.json`、`train_val_expected_hashes.json`、`train.yaml`、`source/`。源码快照、Git状态、权重/数据hash均保留；run产物被Git忽略。`smoke/student_only.pt`只是单步检查产物，不能当作E06正式模型。

准备阶段安排的正式训练与独立Val现已完成，结果见上文。ONNX数值、TensorRT、双目定位与系统Hz仍待后续验收。E01/E05及生产源码、配置、Engine均未覆盖，机器人未访问。

启动、完成标志、恢复及评估命令见 [README.md](README.md)。
