# E2 / E02：第19层 C3k2 内部宽度实验

状态：**候选已由用户完成78轮恢复训练，最佳epoch为48，并已完成独立Val评估**。实验目录按现有规范命名为 `E02_c3k2`。用户提供的 Orin 三轮交错测试结论为：相比 E1，没有取得可测量的推理延迟或系统吞吐收益。完整结果及比较范围见[E1/E2 实验报告](../../benchmarks/E01_E02_REPORT.md)。

只把第19层的 `e` 从0.5改成0.4375：实际输入384、隐藏128→112、输出256，640输入下仍为40×40。其余架构、nc=1、football类别、P3/P4/P5连接及双检测分支保持。它是保守的宽度缩减试验，不代表第19层最冗余或加速最多。

## 新建运行与启动

下方保留准备与启动流程。已有候选run已训练完成；重新实验应先prepare创建新run，不覆盖已有训练输出。从仓库根目录执行：

```bash
cd /home/misaka/workspace

# 创建独立的新run，并更新LOCAL_READY.json指针；不会训练。
/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python -B experiments/E02_c3k2/e02.py prepare

# 可先再次检查配置；不会训练。
bash experiments/E02_c3k2/train.sh --dry-run

# 你准备好后手动启动E2训练。
bash experiments/E02_c3k2/train.sh
```

启动器默认使用E1原CUDA环境 `/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python`，已只读确认RTX4060、Torch2.9.1+cu128、Ultralytics8.4.173。没有安装、升级依赖或改驱动。可用 `FOOTBALL_TRAIN_PYTHON=/path/to/python` 指定同版本环境。

当前独立run位置在本机 `LOCAL_READY.json`；候选初始化为该run下的 `init.pt`，配置为 `train.yaml`。训练结果保存到同run的 `train/`，不会覆盖E1。每次新实验独占创建run；禁止覆盖已有train输出。脚本通过 `script/model-training/train.py` 启动官方训练，没有另一套训练器。

默认沿用E1训练预算：640、batch8、seed42、AdamW lr0=0.001、100 epochs上限、patience30、AMP开启、相同增强。**100是轮数上限，本次候选实际完成78轮。** 新运行初次启动由框架执行其AMP检查，离线时可能跳过辅助模型检查并保留AMP。

## 公平对照

候选从已经训练过的 `baseline/E1_baseline.pt` 迁移，因此不是E0初始化的结构单因素重训。已另准备一个同预算、同E1初始化、保持原架构的control：

```bash
# 也由你手动启动，与E2顺序运行，不要两组抢同一张8GB卡。
bash experiments/E02_c3k2/train.sh --variant control --dry-run
bash experiments/E02_c3k2/train.sh --variant control
```

应比较“E1继续训练control vs E2恢复训练”，另把原E1作为历史参照。目前候选已有训练结果，control仍只有准备记录，不能把额外训练的收益全部归给缩窄结构。两组都重新建立优化器，不是从E1的optimizer断点续训。

## 修改参数 / 创建下一次运行

修改 `train.template.yaml` 后重新prepare；不要修改已准备run的受保护配置，否则启动时会拒绝：

```bash
/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python -B experiments/E02_c3k2/e02.py prepare
/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python -B experiments/E02_c3k2/e02.py prepare --variant control
```

prepare只创建初始化/配置/数据软链接和一次CPU合成前向，不训练、不求loss、不反向传播、不做优化器step、不做Val/Test评估。`LOCAL_READY.json`分别指向最近准备成功的candidate/control；失败准备记录保留在runs，不能当训练结果。

源E1 SHA256固定为 `285c198aff043fe7e7486515dbdc1a2cc02db5daf9a0f55f8ce3c6cabf2743ac`。初始化采用**分支感知的确定性前缀通道迁移**，不是L1/重要性剪枝：split两支、concat各段、C3k内部分支、残差及BN均同步映射；其余层权重逐值复制。没有把不匹配张量留成随机值。迁移表在各run `transfer.json`。

## 数据、预检和后续评估

- 仅引用冻结v1 Train4346张、Val1223张；独立逐文件软链接视图不包含Test，缓存留在run内。
- 原始lists/manifest包含旧绝对路径，E2根据当前 `datasets/v1`、文件名与manifest的usage重建并交叉核对，**不修改冻结名单和元数据**。
- 准备阶段检查标签、名单、审核状态和模型；不读取Test图像/标签，不跑训练集图像解码。训练启动前才逐文件核验Train/Val内容SHA与JPEG结束标记，防止框架修复原图。
- 已完成的预检见[PRECHECK_REPORT.md](PRECHECK_REPORT.md)。初始化权重可完整roundtrip，官方 `DetectionModel.load` 重建后所有张量保留，P3在训练前与源E1逐值相同。训练后P3仍会随权重更新，不能承诺数值不变。
- 已完成的独立Val位于 `experiments/eval/best_val_20261021T025306Z_00e792/`：class0、640、min-conf0.001、工作conf0.45、match-IoU0.5、NMS-IoU0.7、max_det300。mAP50=95.9545%，mAP50–95=78.7770%；详细口径见实验报告和评估inputs_manifest。先冻结候选和阈值再考虑Test；准备脚本本身不生成TensorRT Engine。
- 不自动运行训练、Val、阈值扫描、导出或机器人部署。训练过程中日志保存在run的 `training.log`；中断后不要重复启动同run，用共享训练入口 `--resume <run>/train/weights/last.pt` 明确续训，并保留恢复记录。

`runs/`、初始化PT和本机指针默认Git忽略；小型架构、脚本、计划与预检摘要可审查。未修改E00/E01记录、参考权重或冻结数据。
