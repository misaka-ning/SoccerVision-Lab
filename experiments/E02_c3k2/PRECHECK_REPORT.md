# E02 准备检查记录

2026-10-20（香港时间）。**只完成准备，没有训练。**

候选run：`20261020T102957Z_s42_da66b0_candidate`；control run：`20261020T103046Z_s42_ead857_control`，两者status均prepared，training_started=false，optimizer_steps=0。当前指针在本机LOCAL_READY.json。准备阶段早期失败记录按规范留在runs，不是训练结果。

|检查|结果|
|---|---|
|源E1|baseline/E1_baseline.pt；SHA256 285c198aff043fe7e7486515dbdc1a2cc02db5daf9a0f55f8ce3c6cabf2743ac，与E01_best.pt相同|
|候选改动|只有head[8]/全局19的e=0.4375；隐藏128→112|
|第19层输入/输出|384输入；256×40×40输出|
|P3|1×128×80×80；恢复训练前与E1逐值相同|
|P5|1×512×20×20|
|one-to-many raw|1×5×8400，有限值|
|候选总参数|9,948,638→9,881,630，减少67,008（0.674%）|
|control总参数|9,948,638；结构/权重不缩窄|
|初始化|分支感知前缀映射，未做L1/重要性排序，无随机遗留张量|
|保存/加载|init.pt roundtrip全部state逐值相同；官方DetectionModel.load重建也逐值相同|
|数据|Train4346图/2863框；Val1223图/855框；仅这些split的软链接|
|冻结保护|名单/manifest成员、标签SHA、审核状态通过；Test图像和标签未访问|
|完整图片SHA|准备阶段未逐图核验，用户启动训练时先核验，修改源图会停止|
|迁移测试|4项通过，含“窄模型等于丢弃通道置零的原模型”的前向对照|
|共享训练入口测试|6项通过，使用mock，不启动训练|
|训练dry-run|candidate/control均通过，未创建train/或训练锁|

环境：Python 3.10.12，Torch 2.9.1+cu128，CUDA runtime 12.8，Ultralytics 8.4.173。沙箱中CUDA不可见；已在主机权限下只读核实实际CUDA可用，GPU探针为 `NVIDIA GeForce RTX 4060, 8188 MiB, 6980 MiB, 595.99.02`。复用已有环境，未安装依赖或改驱动。

当前运行时的end2end属性只选择推理分支；E1与准备模型的推理属性均false。两套检测分支权重均保留，init_criterion按one2one分支是否存在选择双分支训练Loss；没有删头或随机重置分类输出。训练、loss、反向、optimizer step、AMP稳定性、GPU batch8显存、Val/Test精度、FLOPs及Orin/TensorRT速度均未实测。本次合成前向在CPU，不能作为性能结果。

核验原始权重和数据后再手动启动训练；完整操作见README。所有大权重、软链接视图、环境快照和运行记录位于Git忽略的runs；小型代码与摘要可审阅。
