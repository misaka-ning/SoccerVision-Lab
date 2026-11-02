# E08 实现验收记录

日期：2026-11-02。审阅基线：`7ab77739828b4e33b3342627fe293e892416d047`。结构化摘要见 [VALIDATION.json](VALIDATION.json)，来源源码SHA见 [DERIVATION.json](DERIVATION.json)。

|验收项|实际结果|
|---|---|
|已有对照/编号|检查main、远端分支/PR及E00–E07；没有等价E05-best无KD继续训练；使用E08|
|E08回归|16项通过；含prepare完整夹具、配置/默认值漂移、hash篡改、输出隔离、跨E07锁、Test读取拦截、缓存指标重算和部分结果拒绝|
|共享训练工具|原有6项测试通过|
|共享评估工具|原有22项测试通过|
|语法|Python编译与两个Shell入口`bash -n`通过|
|离线dry-run|通过；不导入训练运行时、不加载权重；唯一语义差异distill_model|
|真实来源缺失时prepare|按预期失败，在创建正式run和读取数据前列明缺失的E05/E07档案及AMP probe；没有降级绕过|
|初始化|读取仓库发布的models_list/E05_finetuned.pt，5,366,341字节，SHA与E07要求的E05 best完全一致|
|CPU合成smoke|使用上述真实E05 best，合成Train8/Val8；batch8、640；708个状态张量首步前逐值相同；实际optimizer更新1次，366个梯度张量均有限；保存普通学生成功|
|教师未加载|原生KD构造及checkpoint加载钩子记录教师加载0、KD构造尝试0；无投影层；损失仅box/cls/l1；故意构造教师和未声明加载的负向测试均被拦截|
|隔离|smoke前后init SHA不变；重复prepare新建不同目录；已有smoke拒绝覆盖；篡改runtime链接指向Test在训练读取前被拒绝|
|统一口径|1223条合成逐图证据覆盖855GT、410无球图；检查同阈值/FP32/分支/来源，使用共享AP及匹配重算；拒绝伪造Small Recall、改阈值、缺图/乱序、未完成缓存|
|无球FPR|针对一张无球图含两个FP验证FPR=1/1、Precision分母仍按框；零面积候选保留为FP|
|训练预算|CSV73行、最佳43轮的夹具不会被progress74误导；旧更新次数保持not_run；有resume事件但无累积耗时时不冒用最后一段时间|
|共享/历史代码|E05/E06/E07训练入口、共享train.py、共享evaluate.py及指标实现与审阅基线逐字节相同；只在新run存档评估器中应用已说明的零面积准入修复|
|Test与部署|未打开真实Test图片/标注，未启动正式训练、完整真实Val或机器人操作；无部署修改|

运行环境：`/opt/VisionStudio/runtime/bin/python`，Python3.10.12、Torch2.9.1+cpu、Ultralytics8.4.173。GPU环境包版本为Torch2.9.1+cu128，但`torch.cuda.is_available()`为false，nvidia-smi未能连接驱动。

CPU smoke通过并不等于真实训练验收：它用合成图片、CPU、workers0、plots=false、save_period=-1，AMP实际关闭；其它配方保持，初始化真实。未创建正式`preflight.json`。真实Train4346/Val1223准备、CUDA/AMP smoke、E08正式训练及三模型统一Val均为 **not_run**；既无结果也无性能结论。历史E05/E07报告里的结果仍是历史记录，本次不抄成新评估数值。

复现命令（仓库根目录）：

```bash
CPU=/opt/VisionStudio/runtime/bin/python
E08=experiments/E08_warmstart_no_distillation
YOLO_CONFIG_DIR=/tmp/e08-review-yolo MPLCONFIGDIR=/tmp/e08-review-mpl \
  "$CPU" -m unittest discover -s "$E08/tests" -p 'test_*.py' -v
"$CPU" -m unittest discover -s script/model-training/tests -v
"$CPU" -m unittest discover -s script/model-evaluation/tests -v
"$CPU" "$E08/e08.py" dry-run
"$CPU" "$E08/e08.py" compare

# 可选短时CPU合成检查；输出目录必须全新，不作为正式run。
timeout 120s "$CPU" "$E08/tests/cpu_smoke.py" \
  --init models_list/E05_finetuned.pt \
  --output "$E08/runs/local_cpu_smoke_$(date -u +%Y%m%dT%H%M%SZ)"
```

本机原始CPU smoke记录保留于`runs/review_cpu_smoke_01/`和`runs/review_cpu_smoke_02/`，均有界完成一次更新；编译/测试/CLI日志在`runs/review_validation/`。开发时测试夹具语法错误曾导致测试加载失败，修正后最终16项全部通过；失败日志未覆盖。只提交小型验收摘要，不提交权重、合成图片、缓存或运行产物。

用户真实数据启动步骤见 [README.md](README.md#用户启动命令)。先prepare与dry-run、真实CUDA smoke，再由用户手动启动长训练。
