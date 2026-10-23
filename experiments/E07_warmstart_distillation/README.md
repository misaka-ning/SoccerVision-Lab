# E07 / WarmKD：从 E05 最佳足球权重开始蒸馏

按用户要求从E06复制已验证的实验编排入口，只改变学生起点，保留E06作为另一条独立路线。两者使用相同的冻结E01教师和原生特征蒸馏，训练/评估仍调用共享工具，不复制官方训练循环或AP实现。没有复制E06的runs、训练权重、PID或完成标记。

|项目|E06 / KD1|E07 / WarmKD|
|---|---|---|
|学生起点|与E05相同的单类nano初始化`init.pt`|E05训练出的`best.pt`|
|此前足球任务训练|未进行E05的足球微调|使用E05第43轮最佳权重；E05整个任务训练73轮|
|教师|冻结E01 YOLO26s|冻结E01 YOLO26s|
|蒸馏方法|原生P3/P4/P5加权L2、dis=6|相同|
|训练配方|640、batch8、seed42、AdamW、lr0=0.001、AMP、最多100轮、patience30|相同|
|优化器/epoch|新建|新建，不延续E05 optimizer，不使用E05的resume|
|运行产物|E06独立run|E07独立run|

这里E06的“基准起点”指官方nano预训练转成单类后的初始化，不是把E01-s当作学生，也不是完全随机初始化。

本轮比较的主要变量是学生起点，因此暂不同时把E07学习率降低或改成短轮数微调。前面讨论的小学习率方案仍可作为后续单独的新run；当前不能把“相同训练配方”和“小学习率微调”混为同一实验。

## 固定来源与保护

- 教师：`models_list/E01_baseline.pt`，SHA256 `285c198aff043fe7e7486515dbdc1a2cc02db5daf9a0f55f8ce3c6cabf2743ac`。
- E07学生：`experiments/E05_yolo26n/runs/20261023T023231Z_s42_90bcea/train/weights/best.pt`，SHA256 `a51bf6f3ec855e7cb126d097fe30e213d0588d37a9f1d2d9546f090b168dfd13`。
- E06对照run：`20261023T034325Z_s42_KD1_f1347d`，原始初始化SHA与E05起点相同，保持现有脚本及其hash不变。
- 冻结Train4346、Val1223，完整内容hash检查；不打开Test图片/标注。维持640、类别0=football、双训练分支、one-to-many外部NMS验证和部署语义。
- E01/E05/E06原始文件不覆盖；E07拷贝学生权重到自身run的`init.pt`。`DERIVATION.json`记录E06来源源码SHA，源码快照和Git状态保留在run内。
- 本机固定Ultralytics8.4.173 / Torch2.9.1，检查CPU/GPU环境的蒸馏实现hash一致，不升级依赖。

## 启动方式

正式长训练由用户启动，机器人无需开机、无需相机或放球。当前准备与短时验证结果见 [REPORT.md](REPORT.md)。

**同一RTX4060只运行一个实验。先让E06完成，再启动E07；第二个启动命令不会自动排队。** E06/E07共同持有E05已有GPU互斥锁，各自保留独立锁、日志及状态。其他GPU计算进程存在时退出，不终止其他程序。

E06启动命令（保持原样）：

```bash
bash /home/misaka/workspace/experiments/E06_distillation/start_training.sh
```

E06状态显示`trained`、进程已退出后，另行启动E07：

```bash
bash /home/misaka/workspace/experiments/E07_warmstart_distillation/start_training.sh
```

一次性查看E07状态：

```bash
bash /home/misaka/workspace/experiments/E07_warmstart_distillation/status.sh
```

**只有`状态：trained`表示正式训练正常完成**。smoke通过、后台提交成功或进程退出都不能替代此状态。`progress.json`用实际CSV行数计数，并区分最终验证。

E07中断后使用自己的恢复副本：

```bash
bash /home/misaka/workspace/experiments/E07_warmstart_distillation/start_training.sh --resume
```

它恢复的是E07蒸馏模型的投影层、optimizer、scaler及epoch；不是从E05的`last.pt`续训。没有完整恢复副本则拒绝，已有正式train目录不覆盖或改名成train2。

## 训练后对照

```bash
/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python \
  /home/misaka/workspace/experiments/E07_warmstart_distillation/e07.py evaluate --device 0 --conf 0.45
```

校验并复用E01/E05已完成的同口径Val；对E07，以及已训练完成的指定E06对照进行评估，输出`metrics.json`对应的汇总、`comparison.json`和`COMPARISON.md`。若E06未完成，明确标记，不能编造一行实测值。使用CPU或0.25工作点时三/四模型在新目录同口径评估，不混用不同设备/阈值。

优先比较整体AP、Small/Occluded Recall、Precision和无球误报，必要时查看逐图预测与P-R曲线。E06/E07是不同初始化下的同配方开发实验；E07对E05的改善同时含额外训练与蒸馏，仍不能单独证明蒸馏净收益。单seed、早停轮数可能不同，结果不等于统计显著性。

最终部署只保留普通nano，教师及517,888个投影层参数只用于训练。学生仍需训练后ONNX数值验证、Jetson独立构建、双目定位与系统A/B；本次不启动机器人、不修改Engine、功耗、频率、检测阈值或生产配置，不承诺新的系统Hz。

需要另建run时，先显式prepare再smoke；不要覆写当前已检查的run：

```bash
/opt/VisionStudio/runtime/bin/python /home/misaka/workspace/experiments/E07_warmstart_distillation/e07.py prepare
/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python /home/misaka/workspace/experiments/E07_warmstart_distillation/e07.py smoke
```

smoke只更新临时模型，不改变正式初始化。回退时继续使用E01/E05现有模型即可；本轮生产配置没有切换。
