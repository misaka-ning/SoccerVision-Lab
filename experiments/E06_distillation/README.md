# E06 / KD1：E01 → YOLO26n 特征蒸馏

本轮用冻结的 E01 YOLO26s 单类足球模型指导 nano，目标是恢复 E05 在小球、遮挡和整体召回上的损失。仅实施一套 KD1 配置，不进行系数赛马，不调整网络、输入尺寸、检测阈值或生产配置。长训练由用户手动启动。

用户另行安排[E07 / WarmKD](../E07_warmstart_distillation/README.md)，从E05的`best.pt`开始蒸馏。E06仍保持本页的原始单类nano初始化和已冻结脚本；两路线使用相同教师与训练配方。它们共享GPU互斥锁，须先后运行，不自动排队。

## 为什么做这一轮

E05完整独立Val（1223张，conf=0.45、NMS IoU=0.7、max_det=300、FP32 one-to-many）已经完成：

|指标|E01-s 教师|E05-n 无蒸馏|
|---|---:|---:|
|mAP50-95|78.567%|76.846%|
|Precision|97.100%|98.907%|
|整体Recall|90.058%|84.678%|
|Small Recall|86.170%|79.787%|
|Occluded Recall|80.074%|70.111%|
|无球误报图片|12/410|4/410|

nano更保守，部分固定工作点的差异可能来自置信度校准；AP也下降，因此值得验证蒸馏。上述场景有交集，不能把各场景损失加总。其他工具的目测反馈不替代这份同口径定量对照。

## 固定设计

- **教师**：`models_list/E01_baseline.pt`，SHA256 `285c198aff043fe7e7486515dbdc1a2cc02db5daf9a0f55f8ce3c6cabf2743ac`；eval、requires_grad=false、无梯度，检查参数及BN统计不变。
- **学生起点**：E05的FP32单类别`init.pt`，SHA256 `c3da7bd3f2ef6107640c36e8fb34dcef304b195f3115b958612cef711e062710`，逐字节复制到E06独立run。不是从E05最佳权重额外续训。E05未蒸馏模型因此可以作为同起点训练对照。
- **数据及训练配方**：Train4346、Val1223；640、batch8、seed42、AdamW、lr0=0.001、AMP、最多100轮、patience30，增强等设置与E05/E01相同。训练保留双分支，验证/部署采用one-to-many+外部NMS；不打开Test图片/标注。
- **蒸馏**：使用本机已经安装的Ultralytics8.4.173原生`distill_model`，`dis=6.0`（原生默认值）。其余训练参数不变；不安装或升级核心依赖。
- **特征与损失**：学生/教师的L16、L19、L22（P3/P4/P5）经两层1×1 Conv和ReLU投影对齐通道，使用教师分数加权L2，加入原检测损失。当前固定实现先平均教师one-to-many/one-to-one的原始分类logits，再sigmoid生成空间权重；这不是温度KL、框回归蒸馏或伪标签替代人工GT。
- **最终模型**：原生finalize去除教师及投影层，保留普通nano。`resume-last.pt`另存蒸馏包装、投影层、optimizer和epoch，供真实续训。部署batch2仍为FP32`[2,3,640,640] → [2,5,8400]`，A2+Graph无需新增算法路径。

方法文档：[Ultralytics Knowledge Distillation](https://docs.ultralytics.com/guides/knowledge-distillation/)。本轮以本机固定版本源码和`library_contract.json`为准，不套用将来版本的行为，也不将官方COCO收益视为本项目的实验结论。

## 准备、短时验证与训练

入口`e06.py`复用E05的数据检查和冻结配方、共享训练参数解析、官方Trainer及共享Val指标；没有复制训练循环或AP实现。E05历史目录及模型保留不动。

准备过程检查教师/学生hash、E05已有Val的模型与数据来源、全部Train/Val内容，并建立独立缓存视图。随后短时smoke在本地RTX4060只对一个真实Train batch更新一次，验证学生/投影层梯度、教师冻结、保存、原生续训、移除蒸馏模块及独立学生batch2输出。smoke输出仅供工具检查，不作为正式权重，也不改变正式初始化。

当前准备/验证结果见 [REPORT.md](REPORT.md)。完成后在**本地工作站**手动启动长训练，机器人无需开机、无需相机或放球：

```bash
bash /home/misaka/workspace/experiments/E06_distillation/start_training.sh
```

默认Python：`/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python`。E05/E06共享互斥锁，防止训练与smoke并发；启动前发现其他GPU计算进程会退出，不终止其他程序。教师同时驻留增加训练时间和显存，不能用E05耗时直接估计本轮耗时，也不会因显存不足自动降低batch。

一次性查看状态：

```bash
bash /home/misaka/workspace/experiments/E06_distillation/status.sh
```

**只有状态`trained`表示正式训练正常完成**；进程消失或smoke通过不等于训练完成。进度的`epochs_completed`来自实际CSV行数，另标识最终验证，避免E05中回调多计一轮的显示问题。

中断后先检查日志；若已有完整恢复副本：

```bash
bash /home/misaka/workspace/experiments/E06_distillation/start_training.sh --resume
```

无恢复副本不能冒充续训；已存在正式train目录不覆盖、不自动改名为train2。

需要新建运行时，显式prepare，再smoke，不改写旧运行：

```bash
/opt/VisionStudio/runtime/bin/python /home/misaka/workspace/experiments/E06_distillation/e06.py prepare
/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python /home/misaka/workspace/experiments/E06_distillation/e06.py smoke
```

## 训练后评估及判断

```bash
/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python \
  /home/misaka/workspace/experiments/E06_distillation/e06.py evaluate --device 0 --conf 0.45
```

校验并复用E05阶段的E01/E05完整Val，只新评估E06；读取共享工具实际的`metrics.json`，输出三模型`comparison.json`和`COMPARISON.md`。如改用CPU或0.25工作点，则三模型都在新目录重测，不混用不同设备/阈值的P/R。

优先看整体mAP50-95及Small/Occluded Recall是否恢复，同时检查Precision、无球FPR、逐图失败样本和P-R曲线。固定0.45工作点保持不变；置信度校准分析只作为补充，不能通过默默降阈值宣称模型改善。单seed加早停的结果是开发证据，不能独立证明统计显著性；若召回收益伴随明显误报增加，必须明确取舍。

本轮准备不启动机器人、不修改部署文件或Engine，不声称任何新系统Hz。训练后需对普通nano权重重新做ONNX数值检查、目标Jetson独立构建及检测/双目定位和系统A/B；教师/投影层不会随学生部署。若蒸馏无收益，保留负结果，继续使用E01/E05原模型即可回退。
