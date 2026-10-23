# E01：YOLO26s 单类别足球迁移学习

目标是从 `baseline/E0_original_best.pt` 的 80 类 YOLO26s 迁移兼容参数，得到实际检测头 `nc=1`、名称 `{0: football}` 的独立模型。运行身份和实际结果见各 `runs/<UTC>_s42_<suffix>/run_record.json`。这些本地结果默认忽略，不上传权重、图片或预测明细。

## 控制变量

- 固定 v1 Train 4,346 张和 Val 1,223 张，训练不含 Test、Buffer、Heldout unused。
- 不修改任何冻结数据、标签、metadata、manifest 或原始模型。逐文件软链接视图只包含 Train/Val，缓存全部留在运行目录。训练前核验 SHA256、RGB 解码、标签 ID 与审核状态，训练后复核哈希。
- 保持 YOLO26s 架构与双检测分支；官方 `DetectionTrainer.get_model` 按数据集重建类别输出，再调用官方权重迁移。不给分类权重做类别 32 → 0 手术。
- 第一轮单种子 42，640 输入，100 epochs 上限，patience 30，batch 8，AdamW、lr0=0.001、cosine、3 epochs warmup、weight_decay=0.0005，不冻结 Backbone。8 GB RTX 4060 上先实测 batch 8 的 AMP 前向、损失、反向及优化器一步。
- 复用 `script/model-training/train.py` 的配置解析和现有训练 YAML；训练仍使用官方 `YOLO.train`。E01 脚本只编排预检、记录与恢复副本，不引入第二套训练器或指标实现。
- 每 epoch 保存 loss 和 Val 指标，按官方 Val fitness 选择 best。保留 best、last、周期 checkpoint 以及最后一个包含优化器状态的 `resume-last.pt`，防止框架结束时剥离优化器影响恢复。

## 公平评估

E00 来源为 `experiments/E00_original/evaluation` 的完整 **Val** 记录。E01 最佳权重重新加载后使用同一个 `script/model-evaluation/evaluate.py`：640×640、rect=False、候选 conf=0.001、固定工作 conf=0.25、匹配 IoU=0.5、NMS IoU=0.7、max_det=300、相同 AP 和困难场景计算。E00 选类别 32，E01 选类别 0。两者都使用 one-to-many + NMS。为对齐 E00，正式对照评估在 CPU、batch 4、单线程运行；另做统一 GPU 延迟测量。

训练每轮官方 Val 使用框架数据加载器；其矩形批次策略可能与最终公平评估的正方形 letterbox 不同。权重选择按固定官方协议执行，最终对照指标只引用独立公平评估，不混用两类结果。

## 统计及限制

参数量按全部独立加载参数统计。FLOPs 使用同一版本 Ultralytics/THOP、FP32、1×3×640×640，计入当前推理分支和检测头，1 MAC=2 FLOPs；不含预处理、NMS。延迟记录 warmup、重复次数、设备、精度、同步及计时边界，不能解释为 Orin/TensorRT 性能。

不访问 Test 像素和标签，不进行 Test 推理。读取冻结 manifest/metadata 及 split 名单仅用于身份和分集核验。训练、类别数、检测头输出变化同时发生，所有精度/速度变化不能单独归因于类别数。单种子 E01 作为 E02 结构实验的初始对照；论文稳健结论仍需预先固定的多种子复验。

## 版本依据

本机实际 Ultralytics 8.4.173 源码为主要依据：`models/yolo/detect/train.py:get_model`、`nn/tasks.py:BaseModel.load/_remap_cls_by_names`、`nn/modules/head.py:Detect`、`engine/validator.py`。官方说明参见 [YOLO26 双分支与 NMS](https://docs.ultralytics.com/guides/end2end-detection/) 和 [训练参数](https://docs.ultralytics.com/modes/train/)。
