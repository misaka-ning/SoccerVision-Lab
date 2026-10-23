# E05：YOLO26n 单类别足球模型

从官方 YOLO26n 预训练权重开始微调，得到可与 E01-s 对照的 nano 模型。不能将 E01-s 权重改名或直接加载为 nano；两者通道形状不同。本轮先训练和验证普通 nano，蒸馏留待其精度不足时再设计。

## 本轮约束与比较口径

- 使用 E01 的冻结 Train 4346 张、Val 1223 张，不打开 Test 图片/标注。历史名单中的旧绝对路径按 manifest 成员名映射，原始数据不改写；缓存只在 run 内。
- 640、训练 batch8、seed42、AdamW、lr0=0.001、最多100轮、patience30，以及其余增强和优化器配置均与 E01 `train.requested.yaml` 核对。训练 batch8 与部署 batch2 是不同口径。
- 训练保留官方 one-to-many 和 one-to-one 双分支；独立 Val 与部署选择 one-to-many，加外部 NMS。部署固定 FP32 `[2,3,640,640] → [2,5,8400]`，TRT FP16 tactics。
- E01 的 s 初始化已训练过足球，E05 的 n 初始化来自官方通用预训练。这是最终方案对照，不能将所有精度差异都归因于模型尺寸。
- 单独重测两模型同一 Val、相同阈值。默认工作阈值 conf=0.45，另可选0.25与历史表格衔接；NMS IoU=0.7、max_det=300。mAP使用min_conf=0.001保存的候选，P/R/FPR使用对应工作阈值。
- 不覆盖 E01、机器人源码、现有 Engine 或生产 YAML。A2+Graph 保持现有代码；之后加载新 Engine 时由现有运行时重新捕获 Graph，仍需正确性和实机系统 A/B 验收。

## 已实现入口

|文件|用途|
|---|---|
|`e05.py`|数据/初始化预检查、训练/续训编排、共享 Val 工具调用、状态与输入校验|
|`train.template.yaml`|冻结 E01 训练配方，路径在 prepare 时填入|
|`PRETRAINED.json`|官方模型下载来源、版本、SHA256；二进制不提交|
|`start_training.sh` / `status.sh`|后台提交、重复启动保护、一次性查看状态|
|`export_onnx.py`|固定 batch2、opset17、raw FP32 ONNX；原始 PyTorch 与 ORT 数值对照|
|`build_engine_robot.py`|仅在 Jetson TRT8.5.2 构建新候选，生成 raw plan 和带 metadata 的 engine；不部署|
|`tests/test_e05.py`|split、模型身份、冻结配方和输入防篡改检查|

训练继续使用 `script/model-training/train.py` 的参数解析和官方 Trainer；指标继续使用 `script/model-evaluation/evaluate.py`，不另写一套训练器或 AP 算法。

## 训练与状态

本轮`20261023T023231Z_s42_90bcea`已于2026-10-23训练结束并回收检查：73轮、最佳43轮，耗时约39.4分钟。两模型完整独立Val现已完成：nano mAP50-95为76.846%，E01为78.567%；用户决定进入[E06/KD1蒸馏](../E06_distillation/README.md)。不要对已完成run重复启动训练。结果和限制见 [REPORT.md](REPORT.md)。

`LOCAL_READY.json`只记录最后准备成功的目录，其`prepared`字段不是实时训练状态；实时状态以run内`run_record.json`和`status.sh`为准。`progress.json`在本轮最终验证后显示74，实际训练轮数以CSV及完成日志的73为准，细节见报告。

以下启动命令供后续新准备的run使用。在本地工作站运行，机器人不需要开机、相机不需要放球：

```bash
bash /home/misaka/workspace/experiments/E05_yolo26n/start_training.sh
```

默认训练环境为 `/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python`，固定 Ultralytics8.4.173、Torch2.9.1，使用 RTX4060 CUDA0。请避免与其他 GPU 训练/测速并发。脚本返回后台 PID 和唯一日志路径，不需要持续监视。

一次性查看：

```bash
bash /home/misaka/workspace/experiments/E05_yolo26n/status.sh
```

`status: trained` 才表示训练正常结束；进程消失不等于成功。中断/失败先看日志，确认原因后使用同一 run 的恢复副本：

```bash
bash /home/misaka/workspace/experiments/E05_yolo26n/start_training.sh --resume
```

每次模型保存会额外保存有 optimizer 的 `resume-last.pt`；若尚未完成任何 epoch、没有恢复副本，不能续训，应排查后新建 run。原有 train 目录不会被覆盖，也不会自动改名为 train2。

## 训练完成后的 Val 与导出

以下任务可能耗时，按需手动启动。先在同一 Val 比较 E01-s 与 E05-n：

```bash
/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python \
  /home/misaka/workspace/experiments/E05_yolo26n/e05.py evaluate --device 0 --conf 0.45
```

输出为 run 下 `val_0p45_<UTC>/`，含两模型逐图预测、分场景指标及 `COMPARISON.md`。需要衔接 E01 的0.25工作点时另运行 `--conf 0.25`。不能将不同 conf 的 Precision/Recall 直接比较，也不能将本机评估速度当作 Orin 系统 Hz。

若某个模型已完成、后续编排中断，可指定原Val目录续跑。入口读取共享工具实际生成的`metrics.json`，先核验完成标记、模型/数据/评估代码hash、完整Val成员、逐图预测及阈值；通过后复用已完成模型，只运行缺失模型。已有但不完整或参数不匹配的模型目录会报错，保留原始文件，不静默覆盖。

本轮首次Val在E01完成后遇到汇总文件名错误，已修复；继续本轮的命令为：

```bash
/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python \
  /home/misaka/workspace/experiments/E05_yolo26n/e05.py evaluate --device 0 --conf 0.45 \
  --continue-evaluation /home/misaka/workspace/experiments/E05_yolo26n/runs/20261023T023231Z_s42_90bcea/val_0p45_20261023T032229Z
```

加`--dry-run`只检查续跑计划，不启动预测。原训练源码与受保护输入manifest保留不动；这次训练后的编排修复以源码副本、差异和新旧SHA追加记录在run的`post_training_revisions/`，仅允许已训练run使用。模型、数据、配置和共享指标代码仍执行原始hash检查。

确认精度满足要求后，在本地 CPU 导出：

```bash
/opt/VisionStudio/runtime/bin/python \
  /home/misaka/workspace/experiments/E05_yolo26n/export_onnx.py
```

输出 run 的 `export/`，拒绝覆盖。导出只选择 one-to-many、不嵌入 NMS，并以零、随机、真实 Val 双图三组输入对照未融合 PyTorch。坐标最大误差门槛0.05像素、分数绝对误差门槛1e-4；记录实际值。该验收不代替训练后检测与机器人 TRT/双目定位验收。

导出依赖使用 CPU 环境已有 ONNX1.17.0，ORT1.20.1及其辅助包只安装于本实验 `.deps/ort`，不改现有训练/部署环境。重建隔离依赖：

```bash
/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python -m pip install \
  --target /home/misaka/workspace/experiments/E05_yolo26n/.deps/ort --no-deps \
  onnxruntime==1.20.1 flatbuffers==24.3.25 coloredlogs==15.0.1 humanfriendly==10.0
```

## 机器人阶段

训练与 Val 完成后再安排安全测试窗口。将正式 `export/` 目录和 `build_engine_robot.py` 拷贝至机器人独立 E05 测试目录，使用其原有 TensorRT Python 环境运行：

```bash
python3 build_engine_robot.py --export-dir <机器人上的export目录> \
  --output-dir <尚不存在的E05构建目录>
```

构建脚本拒绝未训练初始化、错误 ONNX SHA、错误 TRT版本或非固定 batch2/FP32 I/O。构建失败保留目录与日志，不自动修改功耗、频率、模型或生产文件。

本轮还需要后续实测：同一输入的 PyTorch/ONNX/TRT 检测对照、小球/遮挡/模糊/无球误检、双目匹配/三维定位，以及当前 MAXN+A2+Graph 下 E01-s / E05-n 的交错系统 A/B。维持生产相同 conf/NMS/相机/功能，记录 Hz、延迟分布与有效定位率；没有这些数据，不承诺25/30Hz。当前入口不会自动启动机器人或 ROS。

## 重新准备与回退

新建一轮预检查（CPU，含完整 Train/Val SHA 校验）：

```bash
/opt/VisionStudio/runtime/bin/python /home/misaka/workspace/experiments/E05_yolo26n/e05.py prepare
```

每轮保留唯一目录、源码快照、Git状态、模型/数据hash、迁移清单、运行环境、训练请求/有效参数、epoch进度与恢复记录。`LOCAL_READY.json` 指向最后成功准备的 run，不应在训练中随意重新 prepare。源码或输入变化后旧 run 拒绝启动，应调查后新建 run。

本轮没有修改生产配置，停止 E05 任务即可继续使用 E01；将来若部署候选，回退需重新选择原 E01 Engine 并重启感知进程，让原 Engine 重建自己的 Graph。
