# 机器人视觉系统推理加速：技术原理复盘

资料截止：2026-10-23，Asia/Hong_Kong。对象：Jetson Orin NX 16GB、ZED Mini、E01 足球单类别 YOLO26s、TensorRT、双目定位和 ROS2 感知链路。

本文用于技术沟通、面试和论文表述。本次只阅读源码、已有实验记录，并离线解析已有 ONNX 的图结构；没有执行模型推理、训练、新 benchmark、机器人操作或修改生产程序。

## 1. 先把“做过什么”和“证明了什么”分开

### 1.1 当前状态与历史记录的时间顺序

| 时间与材料 | 当时的事实 | 今天应如何理解 |
| --- | --- | --- |
| E01 | 建立单类别足球模型，完成微调与 Val | 当前主要使用的模型；精度成果不等于部署加速成果 |
| E02_c3k2 | 缩窄第19层内部通道、恢复训练 | 结构实验已完成，但未获得实机加速；不是当前主部署模型 |
| E03，10月21日 | 25W、GPU上限408MHz；定位计算、复制、提交及后处理成本 | 是瓶颈证据；当时 Graph 尚未接入正式节点 |
| E04 阶段报告，10月22日 | A2+Graph 在隔离实验中获得可重复收益，当时尚未生产接入 | 保留报告的历史状态，不能将“未采用”当成永久结论 |
| E01_a2_graph_20261022T103907Z 接入记录 | 已将 E01+A2+Graph 接入本地源码、机器人源码和安装副本 | 当前默认启动路径已接入；这不等于长期稳定性和物理定位精度全面验收 |
| 10月23日 runtime_capture 记录 | 确认每次加载都重新捕获；补连续重载测试 | 构建脚本不捕获，运行进程自己捕获 |
| 10月23日 MAXN 预处理调查 | 已有 MAXN mode0、GPU动态范围306～918MHz；源/安装版A2、Graph一致 | 约23Hz为用户观察值，新轮正式筛选/系统A/B仍待采集 |

来源：[E04阶段报告](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/REPORT.md)、[正式接入记录](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/integration/E01_a2_graph_20261022T103907Z/INTEGRATION_REPORT.md)、[安装验收JSON](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/integration/E01_a2_graph_20261022T103907Z/robot_validation/verification.json)、[MAXN后续调查](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/preprocess_race/20261023T014627Z/REPORT.md)。

“已部署”在本文指源码、安装副本和默认配置已接入。运行中是否真正使用 Graph，还必须看 effective、capture_count 和 fallback_count；不能只看 YAML。本文没有重新检查当前常驻进程。

### 1.2 六类优化分别改动什么

| 类型 | 本项目实例 | 改变的对象 | 不应混淆的概念 |
| --- | --- | --- | --- |
| 模型结构/任务适配 | E01单类别；E02内部通道缩窄 | 检测头或网络通道、训练权重 | 参数量下降不保证延迟下降 |
| TensorRT推理优化 | FP16 tactics、构建时融合和布局选择 | Engine内部执行方案 | YAML half不等于全部层及I/O均FP16 |
| GPU执行调度 | CUDA Graph | CPU提交GPU工作的方式 | Graph不是把全部算子融合成一个kernel |
| GPU/CPU数据传输 | A2最终框合并回传 | 回传次数、同步边界和数据组织 | A2没有替换NMS，也不是传回全部8400框 |
| 图像预处理 | C2 host打包缓冲复用；canvas/reuse候选 | Resize/Letterbox周边复制与分配 | CPU画布复用不是GPU Resize |
| Jetson功耗/频率 | 25W与后来的MAXN | 硬件资源、频率上限和调频空间 | MAXN不是锁频，也不是代码算法优化 |

### 1.3 模型与版本身份

主部署源码：/home/misaka/soccer_backend_tensorrt。机器人部署根：/home/nvidia/soccer_backend_tensorrt。机器人安装包位于 install/soccer_perception_ros/lib/python3.8/site-packages/soccer_perception。

| 对象 | 身份 |
| --- | --- |
| E01 PT SHA256 | `285c198aff043fe7e7486515dbdc1a2cc02db5daf9a0f55f8ce3c6cabf2743ac` |
| E01 Engine SHA256 | `98c1b6bc703b29874d95db94d9cf51ef5b4a4142a7ca6cf22362a0c616fbf348` |
| 当前 Graph 源码 SHA256 | `85aee1a4427bb6c558273f87d34a6a349a148a7b2f0b4b97b7d6ab190ad6f695` |
| 部署栈 | JetPack5.1.5，TensorRT8.5.2.2，Torch2.0.0+nv23.05，Ultralytics8.3.159 |
| 模型接口 | one-to-many，外部NMS；FP32输入输出、Engine内部允许FP16 tactics |
| 当前默认选择 | E01_baseline.engine；yolo_optimization=a2_graph |

当前源码行号以本次阅读时为准，后续编辑可能移动。E04源/安装一致性的最新已有证据还包括[10月23日冻结清单](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/preprocess_race/20261023T014627Z/frozen.json)和[只读就绪记录](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/preprocess_race/20261023T014627Z/robot_ready.txt)。本地训练环境的Ultralytics8.4.173与机器人8.3.159不同，不能互相冒充。

## 2. 当前完整数据流与计时边界

~~~mermaid
flowchart LR
  A["同一次ZED读取：左图、右图"] --> B["CPU Resize / Letterbox / RGB / BCHW"]
  B --> C["传输、FP32转换和归一化"]
  C --> D["TensorRT：Graph更新输入并Replay"]
  D --> E["原置信度过滤、NMS、坐标恢复"]
  E --> F["A2：最终框一次合并回传CPU"]
  F --> G["按目构造候选、排序、top-k"]
  G --> H["双目匹配、三角化、跟踪"]
  H --> I["ROS调度与发布"]
~~~

### 2.1 Shape怎样变化

~~~text
左/右图：各 uint8 BGR [376,672,3]（当前VGA场景示例）
  → 各 Letterbox [640,640,3]，padding=114
  → CPU uint8 RGB BCHW [2,3,640,640]
  → GPU FP32 /255 [2,3,640,640]
  → TensorRT raw FP32 [2,5,8400]
  → 每目过滤/NMS/恢复坐标后的 FP32 [N_left,6]、[N_right,6]
  → A2 CPU [N_left+N_right,6]，再切回各目
  → Python BallDetection候选 → 每目稳定排序后最多top-k=5
  → 匹配后的左右球心 → 3D位置 → 跟踪 → ROS
~~~

8400=80×80+40×40+20×20，是三个尺度的候选位置总数；5表示四个已解码框坐标通道和一个足球分数，不是“五个类别”。六列最终框才是 x1,y1,x2,y2,score,class。Engine并没有在内部做NMS。

640方形输入、batch2固定。conf=0.45、NMS IoU=0.7、max_det=300、class0、top-k5是E04被测配置。top-k在适配器最后执行，不能偷偷提前截断以获得更低耗时。对应入口：[左右目顺序](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/pipeline.py:243)、[候选转换与末尾排序](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/adapters/yolo.py:358)。

原始FP32输入占9,830,400B；uint8打包输入占2,457,600B；raw FP32输出占336,000B。这些是按shape计算的数据量，不是实测带宽或传输耗时。

### 2.2 下面几种“毫秒”不能混用

| 指标 | 范围与限制 |
| --- | --- |
| Engine CUDA event | 取决于事件包围范围；常驻输入纯执行与包含Graph输入复制/输出clone的forward不同 |
| enqueue/inference方法墙钟 | 异步返回可能只表示提交完成，不代表GPU已算完 |
| postprocess/A2 pack墙钟 | 可能含CPU执行、GPU工作等待和阻塞回传 |
| 完整检测器墙钟 | 从左右图输入到候选列表返回，包含预处理、推理、后处理、结果转换 |
| system cycle | 还含采集、定位、跟踪、输出等待和可选可视化 |
| processing/publish Hz | 按工具的有效时间窗口计数；单位为双目帧对/秒，不乘2 |
| 读取完成至发布 | 不包含曝光、相机内部缓冲及控制端接收；不能称完整传感器到执行器延迟 |

CPU方法墙钟、GPU事件和CUDA API等待可能重叠，不能把它们直接相加。本文的均值、分位数、宏平均均沿用对应实验定义。

### 2.3 E03为什么把优先级从“改网络”转到“改链路”

原E01逐层profile的互斥分组为：Backbone扣除Attention约37.99%，Neck扣除内嵌PSA约21.41%，Attention块约10.39%，Detect约14.15%，Reformat/Copy等辅助约16.05%。分母是带profiler影响的28.48785ms合计，不是正常28.135ms的精确拆账。

Nsight检测器固定图trace窗口4045.341ms，目标应用GPU活动并集1839.851ms，约45.48%；其余约54.52%没有目标应用GPU活动。它说明整条检测路径存在GPU之外的处理/等待，不证明其他进程也没有使用GPU，更不证明所有空档都能被Graph消除。trace有采集开销，不能拿其中67ms级迭代墙钟替代无Nsight的正常计时。[E03时间线与边界解释](/home/misaka/workspace/experiments/E03_tensorrt_profiling/REPORT.md)

固定batch2、静态shape和原AutoBackend复用context都是既有设计，不是E04新增的三份独立提速。E03开启Viser、E04正式组合关闭Viser也是跨阶段条件差异，不能全算成A2/Graph收益。

## 3. E01：任务适配是技术路线起点，不是已经证明的速度提升

E01把原80类模型改为足球单类别，类别32映射为0，迁移兼容张量并微调。Train4346张、Val1223张，640、batch8、seed42、AdamW；实际训练74轮，最佳checkpoint对应epoch44。源权重兼容迁移696/708个状态张量，重建两套检测分支、三个尺度的最终分类张量。

实现见[e01.py的单类别迁移](/home/misaka/workspace/experiments/E01_baseline/e01.py:213)和[独立模型确认](/home/misaka/workspace/experiments/E01_baseline/measure.py:51)。训练保留双分支；部署选one-to-many并执行外部NMS。训练AMP是训练数值策略，与部署Engine启用FP16是不同阶段。

在相同历史Val口径下，E0→E01的mAP50为60.2318%→96.0161%，mAP50–95为55.4108%→78.5508%；conf0.25时Recall为43.3918%→91.9298%，但Precision由99.4638%降至94.9275%，无球误报也增加。不能说所有指标全面提升。以上是Val，不是独立Test成绩。

分类通道变少在理论上可降低检测头成本，但历史RTX4060、batch1、FP32、已融合one-to-many前向仅为6.6431→6.6115ms，记录未认定明显加速；它不是Orin端到端对照。来源：[E01/E02汇总](/home/misaka/workspace/benchmarks/E01_E02_REPORT.md)。

面试表述：“先通过单类别迁移和微调解决足球检出能力，再把部署性能作为独立问题测量；没有把精度提高或类别减少直接说成机器人提速。”

## 4. TensorRT FP16：优化Engine内部计算

### 4.1 原流程和问题

通用框架前向需要解释/调度计算图，FP32权重和激活还会产生较大的算术与访存成本。但项目没有一组同条件的“原PyTorch/纯FP32 Engine vs 当前FP16 Engine”正式数据，不能虚构它们的速度差。

### 4.2 修改后的流程

已有模型导出ONNX，在目标Orin上构建TensorRT Engine；构建器进行常量折叠、融合、布局/tactic选择，并允许较低精度实现。日常启动直接加载既有Engine，不重新导出或重建。

### 4.3 真实代码入口

| 文件、函数 | 关键行的作用 |
| --- | --- |
| [model_artifacts.build_engine](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/model_artifacts.py:143) | format=engine，half取自_trt_export_half，传imgsz/batch/dynamic；这是当前显式构建入口，不是旧Engine生成全过程的日志 |
| [YoloBallDetector._trt_export_half](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/adapters/yolo.py:308) | 根据实际TRT/Python环境决定导出请求；不能仅凭YAML推断精度 |
| [model_artifacts.require_engine](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/model_artifacts.py:70) | 只加载现有Engine，显式.engine不要求PT sidecar |
| [E03 builds](/home/misaka/workspace/experiments/E03_tensorrt_profiling/execute_robot.py:62) | 独立诊断构建实际使用--fp16，同时明确input/output为fp32:chw、workspace2048MiB |
| [机器人冻结AutoBackend](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/runs/20261022T020842Z_78f1b7/audit/source/installed/ultralytics_0/nn/autobackend.py:391) | 从Engine binding dtype推断外部精度；不靠half=true强制改输入 |

### 4.4 容易理解的原理

FP16每个元素16bit，FP32为32bit。合适的卷积和矩阵运算可以降低数据访问量，并选择适合Tensor Core的实现。TensorRT的FP16构建选项是允许选择FP16 tactic，不是命令所有算子都必须FP16；累加精度也不能只从输入dtype推断。[TensorRT8.5 BuilderFlag定义](https://github.com/NVIDIA/TensorRT/blob/release/8.5/include/NvInfer.h#L7943-L7946)

可以理解成“允许工厂为合适工序使用更快的加工设备”；不是将整个工厂的所有材料格式统一改掉。

### 4.5 数据流与Shape

外部始终为FP32 [2,3,640,640]→[2,5,8400]。E03新detailed图显示输入Reformat可转为FP16布局，后续许多卷积为FP16；也存在格式转换、Copy和不同执行类型。

因此，Graph校验backend.fp16=false完全可以与“Engine内部使用FP16 tactics”同时成立：前者在此表示外部输入binding不是FP16。

### 4.6 为什么可能更快

潜在收益来自适合硬件的卷积/矩阵实现、减少内部元素字节数和融合后更少的中间访问。收益受shape、布局、带宽、转换和其他CPU成本限制，不能承诺两倍加速。

### 4.7 真实结果与局限

E03原E01 Engine为28.13498ms/batch2，P95=28.17087ms；条件是25W、GPU上限408MHz、动态时钟，GPU常驻输入，100预热、三轮各60秒、交错执行，正常计时不挂profiler/Nsight。

这证明“当前Engine的执行成本”，没有单独识别FP16相对FP32的收益。新detailed图只能解释新图的实际dtype/tactic，不能把其内部元数据移植到只有layer_names_only的旧Engine。[E03报告](/home/misaka/workspace/experiments/E03_tensorrt_profiling/REPORT.md)、[详细元数据](/home/misaka/workspace/experiments/E03_tensorrt_profiling/results/TOP20.md)。

### 4.8 是否改变输出、精度和协议

外部shape、类别和定位协议不变；低精度可能带来舍入误差，不能保证原始输出逐位相同。E03旧Engine与新候选的64张Val对照通过冻结阈值：E01保留框43/43、匹配框最大坐标差0.125px；这是Engine间一致性检查，不是FP32→FP16独立精度实验或全量AP/物理定位精度证明。

### 4.9 当前部署状态

**已使用既有TensorRT Engine，内部FP16 tactics，外部FP32。** E04没有因此重新构建或覆盖E01 Engine。FP16 I/O和INT8是另外的候选，尚未用于当前路径。

### 4.10 面试追问

- “half=true是否表示输入就是FP16？”——不表示；已有Engine由binding决定，本项目输入输出实际为FP32。
- “FP16提速多少？”——没有独立FP32/FP16配对结果，不能给出百分比；可以给当前Engine的28.135ms及明确条件。
- “为什么在机器人构建？”——目标设备的TRT/CUDA栈和硬件会影响可用tactic及兼容性，不能把本地不同版本Engine默认视为等价产物。

## 5. Conv–BN融合：把推理期的固定线性变换折叠进卷积

### 5.1 原流程和问题

未融合模块执行Conv→BN→SiLU。BN在推理时使用固定的running mean/variance，仍作为独立节点执行会增加中间特征读写和调度。训练时统计量的行为不同，不能直接照此消除BN。

### 5.2 修改后的流程

将BN的缩放和平移折进卷积权重、bias，执行Conv'→SiLU。它是代数等价的推理图变换，不是E02那样删除通道，也不是E04新写的优化内核。

### 5.3 真实源码与已有产物证据

E01训练/测量环境Ultralytics8.4.173：

| 文件、函数 | 关键代码 |
| --- | --- |
| [Conv.forward与forward_fuse](/home/misaka/.local/share/vision-studio/gpu-runtime/lib/python3.10/site-packages/ultralytics/nn/modules/conv.py:78) | 第87行act(bn(conv(x)))；第98行act(conv(x)) |
| [BaseModel.fuse](/home/misaka/.local/share/vision-studio/gpu-runtime/lib/python3.10/site-packages/ultralytics/nn/tasks.py:243) | 第263–265行折叠参数、删除bn、切换forward |
| [fuse_conv_and_bn](/home/misaka/.local/share/vision-studio/gpu-runtime/lib/python3.10/site-packages/ultralytics/utils/torch_utils.py:382) | 第397–398行将卷积和BN参数传入fuse_conv_bn_weights |
| [Exporter](/home/misaka/.local/share/vision-studio/gpu-runtime/lib/python3.10/site-packages/ultralytics/engine/exporter.py:900) | eval、float，然后model.fuse |
| [E01 measure](/home/misaka/workspace/experiments/E01_baseline/measure.py:63) | 明确设置one-to-many并m.fuse(verbose=False) |
| [机器人8.3.159 AutoBackend快照](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/runs/20261022T020842Z_78f1b7/audit/source/installed/ultralytics_0/nn/autobackend.py:200) | PT加载路径启用fuse；Engine路径加载已构建图，不在每帧重新融合 |

这些版本与用途分别标注，未将8.4.173导出器逐行冒充机器人8.3.159的构建源码。本次只读解析E03已归档ONNX，得到：

| 已有文件 | Conv数 | BatchNormalization数 | 总节点 | 外部输入→输出 |
| --- | ---: | ---: | ---: | --- |
| [E01 ONNX](/home/misaka/workspace/experiments/E03_tensorrt_profiling/runs/20261021T080741Z_824b47/inputs/E01_baseline.onnx) | 102 | 0 | 402 | [2,3,640,640]→[2,5,8400] |
| [E02 ONNX](/home/misaka/workspace/experiments/E03_tensorrt_profiling/runs/20261021T080741Z_824b47/inputs/E02_c3k2.onnx) | 102 | 0 | 403 | 同上 |

两份ONNX的SHA256分别为18b0a86979b053ffaa82e6b3eec0df7a0a36cf6146b6cb719c3269b58ae16074和94b2a3128c990a02fcb88def59ac7b4caa48e130c63a2d013b0e70ab0bd5f3d7。这是静态图读取，不是新推理实验。它确认交给TRT的图没有显式BN节点，但不能据102个Conv推算“恰好融合102对BN”，也不能凭此还原历史各编译pass的耗时贡献。

### 5.4 计算机原理与公式

对输出通道c：

~~~text
z_c = W_c * x + b_c
BN(z_c) = gamma_c * (z_c - mean_c) / sqrt(var_c + eps) + beta_c

a_c  = gamma_c / sqrt(var_c + eps)
W'_c = a_c * W_c
b'_c = a_c * (b_c - mean_c) + beta_c

于是 BN(Conv(x)) = Conv'(x)
~~~

没有bias时令b=0。可以把它理解成“把每次做完卷积后的固定校准，提前算进卷积参数”。推理eval模式和已计算的running统计量是前提。[PyTorch官方融合接口说明](https://docs.pytorch.org/docs/main/generated/torch.nn.utils.fuse_conv_bn_eval.html)

### 5.5 Shape与数据流

输入[B,Cin,H,W]→卷积输出[B,Cout,H',W']→BN同shape→SiLU，变为输入→Conv'同shape→SiLU。权重仍为[Cout,Cin/groups,kH,kW]，只是数值更新，并可能新增bias；通道和空间尺寸不变。

### 5.6 为什么可能提速

消除单独BN计算及其中间读写/launch。TensorRT还可能继续融合卷积与激活，但“BN参数折叠”和“Conv+SiLU执行融合”是两个层次；不能把所有层名中的“+SiLU”都说成手写Conv-BN融合。

### 5.7 真实结果与局限

本项目没有保存同条件融合开/关的独立性能A/B，**融合单项提速未量化**。E01已融合前向计时、已有ONNX无显式BN和E03融合执行层记录支持其存在，不支持另编一个节省毫秒数。E03的28.135ms已经是现有部署图成本，不能再把“将来融合BN”的收益重复算进去。

### 5.8 输出与精度影响

固定统计量下实数代数等价，浮点重排可能带来小误差；shape、类别、NMS和定位协议不变。不能用训练阶段当前batch统计量套用固定BN折叠公式。

### 5.9 当前部署状态

**已有导出/编译工具链使用的推理图优化，非E04新增成果。** 当前Engine加载的是既有优化图，不会每帧重新折叠。没有“E04手工融合BN获得独立X%”的结论。

### 5.10 面试追问

- “这是剪枝吗？”——不是，形状不变，是固定仿射变换的参数重写。
- “为什么训练时不直接去掉？”——训练BN依赖batch统计、参与训练动态，不能等同推理固定统计。
- “能不能继续融合提速？”——已融合部分不能重复获益；需先看真实Engine里还剩什么，而不是重复调用fuse。

## 6. A2：双目最终检测结果合并回传

### 6.1 原流程和实际问题

原Ultralytics已完成置信度过滤、NMS、坐标恢复，然后适配器逐目读取xyxy、conf、cls，各自执行detach().cpu().numpy()。左右目均非空时，适配器存在最多六个GPU→CPU转换入口；它们传回的是最终少量框，**不是8400个原始候选**。

E03固定图回放中，两目候选转换方法合计4.067ms，完整检测器58.986ms。该方法边界含等待/转换/构造，不能把4.067ms全部称作物理DMA传输耗时。

### 6.2 修改后的流程

~~~text
原NMS、坐标恢复：
  left CUDA [N_left,6] + right CUDA [N_right,6]
    → torch.cat(dim=0)
    → 一次 blocking .cpu()
    → 浅拷贝Results/Boxes，按原行数切回左右CPU视图
    → 原候选转换器、原稳定排序、原top-k
~~~

下游仍调用原来的三项.cpu()接口，但输入已在CPU，**不再产生这几次GPU回传**；不能声称把源码中所有.cpu()调用都删掉了。

### 6.3 真实调用、代码和关键行

| 位置 | 发生的事情 |
| --- | --- |
| [postprocess.PostprocessHandle.__init__](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/postprocess.py:55) | 只包装当前detector.model实例的predict，不改全局Ultralytics |
| [predict包装器](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/postprocess.py:62) | 第64行先调用original_predict；第68行再打包，保证原NMS和坐标恢复在前 |
| [_pack_final_results](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/postprocess.py:116) | 检查list、FP32、普通六列Boxes、同device、无mask |
| [cat与回传](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/postprocess.py:137) | 第141行torch.cat，第142行packed.cpu；全空时直接返回 |
| [按目拆分](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/postprocess.py:145) | 第150–159行浅拷贝、清理缓存属性并切片，不改原Results |
| [原候选转换](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/adapters/yolo.py:366) | 三个CPU数组入口仍在；第400–401行稳定排序后top-k |
| [生产开关映射](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/__init__.py:11) | a2_graph映射postprocess=a2、engine=graph、preprocess=c0 |

关键代码的实际顺序是：

~~~python
results = original_predict(*args, **kwargs)
# _pack_final_results内部
packed = torch.cat(tensors, dim=0)
host = packed.cpu()
new_boxes.data = host[start:start + count]
~~~

### 6.4 原理：减少交接次数，而不是主要减少字节

GPU工作通过stream异步执行，CPU需要实际框数值时必须等待数据可用。多个很小的回传可能被API、分配、同步和Python控制开销主导。把小件合成一次交接，可能比逐项领取更省时，但GPU cat本身也有成本。

Orin是统一物理内存平台，不是独显经PCIe搬运；这不意味着普通Torch CPU/CUDA Tensor自动零拷贝。.cpu()仍涉及实际实现中的存储转换/复制及完成性要求，不能用“共享LPDDR”推断没有回传和同步成本。

### 6.5 Shape、顺序和内存归属

每行六个FP32共24B。左右各1框时，总有效数据48B；合并前后数据量基本相同，主要改变次数。host切片保持输入目顺序和每目行数，空目也不串位。CPU storage由本次结果持有，下一帧不会覆盖旧结果。

A2打包的是NMS后的全部最终框，再由原代码做top-k；NMS max_det与应用top-k是不同层次。支持范围之外或打包异常时，返回**同一次推理**的原结果并记录fallback，不重新跑模型、不重放旧帧。

### 6.6 为什么可能提速，以及不能归因什么

可能减少适配器的重复设备交接和等待，尤其是小结果的固定开销。A2没有改变卷积计算、NMS计算和原raw输出；也不是异步D2H、pinned memory、零拷贝或三维双目融合算法。只看原converter耗时下降会漏掉移入predict包装器的pack成本，必须比较完整检测器/系统墙钟。

### 6.7 真实结果与局限：25W E04 phase5

100预热、每作业60秒、三轮交错首尾R0，固定相机有球，Viser关闭；有效system窗口GPU采样均408MHz，温度约50.781～52.625°C。

| 指标 | R0 | A2 |
| --- | ---: | ---: |
| 固定Val检测器均值 | 59.009ms | 56.074ms |
| 有球系统检测器均值 | 61.070ms | 58.739ms |
| 系统processing Hz | 14.580 | 15.100 |
| 读取完成至发布均值 | 63.943ms | 61.548ms |
| 同范围P95 / P99 | 67.053 / 71.183ms | 65.131 / 71.022ms |

三轮配对processing Hz宏平均+3.566%，读取完成至发布平均节省2.397ms。它不是简单用表中池化均值相减或相除得到的宏平均。第3轮A2的read-ready P99比该轮首尾基线分位数平均高1.373ms；不能宣称尾延迟总是改善。

更早phase3同期A2为+4.786%，那是另一批次，不能挑更大百分比与phase5混写。无球时A2可能根本没有D2H，不足以验证有球收益。来源：[正式性能表](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/PERFORMANCE_COMPARISON.md)、[A报告与计数](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/AGENT_A_REPORT.md)。

### 6.8 输出、精度和定位协议

模型raw、NMS/阈值、坐标恢复、顺序、top-k及每目归属不变；改变的是内部Results中Boxes存储设备。E04的61对Val及组合对照覆盖输入/raw/最终框/候选/匹配/定位/跟踪/ROS，组合732数组精确一致。固定样本等价不等于全量AP或物理距离真值验证。

### 6.9 当前部署状态

**已接入正常启动路径，a2_graph默认启用；原NMS仍是Torch fallback。** a2单独模式可用，none可回滚。A2不兼容的旧实验predictor开关会在加载前被拒绝，避免两套后处理叠加。

### 6.10 面试追问

- “A2是不是更快的NMS？”——不是，它在原NMS之后合并结果回传。
- “只传几十字节为何能省毫秒？”——固定交接和等待可能比有效数据量更重要；毫秒收益以整链路A/B为准，不能只按带宽计算。
- “会把左右目混在一起吗？”——cat后按原行数和目顺序切片，不做跨目NMS。
- “是不是减少候选换速度？”——没有；过滤、max_det、top-k和执行顺序都保持。

## 7. CUDA Graph：减少重复提交，保留同一Engine计算

### 7.1 原流程和问题

机器人冻结的[AutoBackend.forward](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/runs/20261022T020842Z_78f1b7/audit/source/installed/ultralytics_0/nn/autobackend.py:716)每次更新images地址，调用context.execute_v2，然后返回输出binding；没有Graph捕获或Replay。

一次Engine执行会涉及很多GPU工作。CPU逐次提交存在固定成本；若GPU等提交，事件包围的时间也可能包含这些间隙。E03普通Engine trace每次约197个kernel；“一个TRT执行层”“一个kernel”“一次enqueue”不是同一个单位。

### 7.2 修改后的实际流程

~~~text
每次启动/模型load：
  原predict(batch2黑图)建立真实Predictor/AutoBackend，丢弃结果
  → 挂接Graph/A2，预处理仍c0
  → 再次predict(batch2黑图)，丢弃结果
       Graph创建自己的context、stream及稳定I/O
       → 图外3次enqueue预热并同步
       → 捕获一次TRT enqueue
       → 执行Replay并同步确认
  → 开始正式双目处理

每次正式前向：
  等待调用流先前工作
  → 当前预处理Tensor复制到Graph稳定输入
  → Replay已捕获的TRT工作
  → 图外clone本次raw输出
  → 调用流等待输出可用
  → 原NMS/坐标恢复 → A2 → 定位/ROS
~~~

“捕获一次”指每次成功初始化的生命周期，不是整个机器人只捕获一次，也不是每帧捕获。捕获失败的fallback不能被称作Graph生效。

### 7.3 真实源码与关键行

| 文件、函数 | 关键点 |
| --- | --- |
| [YoloBallDetector.load](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/adapters/yolo.py:149) | 已有模型/handle先close，再创建当前模型；不会复用旧模型Graph |
| [_initialize_optimizations](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/adapters/yolo.py:230) | 第238行原predict；239行安装；240行优化predict；241行同步；启动结果不返回业务 |
| [Graph校验](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/graph.py:44) | 严格限制静态TRT8.x、CUDA、FP32 BCHW、两个binding及固定shape |
| [_CudaGraphRunner._initialize](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/graph.py:89) | 第93行私有stream；95–102行稳定输入/输出和独立context/地址；106–109行预热同步 |
| [真正捕获](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/graph.py:110) | 第113–115行torch.cuda.graph内执行_enqueue并计数 |
| [_CudaGraphRunner.run](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/graph.py:117) | 第128行更新当前输入；131行replay；135行clone；137–138行流等待与生命周期记录 |
| [execute_async_v2](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/graph.py:82) | 使用自有context、binding地址及stream，检查enqueue成功 |
| [GraphHandle._forward](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/graph.py:217) | 失败记录原因；可安全清理时回原forward；清理失败拒绝不安全回退 |
| [资源释放](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/graph.py:145) | 同步后释放图、context、buffer、stream；restore还核对hook所有权 |
| [生产close](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/adapters/yolo.py:261) | 撤销失败时保留handle/model供重试，不假装已经释放 |

最关键的实际执行顺序：

~~~python
self.stream.wait_stream(caller)
self.input.copy_(im, non_blocking=True)
im.record_stream(self.stream)
self.graph.replay()
result = self.output.clone()
# 离开私有stream上下文后
caller.wait_stream(self.stream)
result.record_stream(caller)
~~~

这里的copy是GPU预处理Tensor到稳定GPU输入的复制，不是把相机原图直接送入Graph。

### 7.4 原理：记录执行安排，而不是记录上一帧答案

把固定GPU工作及其依赖关系预先记录成图，之后以Replay提交。类比“每次逐条下发工单”变为“执行预先登记的整套工单”。记录的是操作、地址和依赖，输入内容仍可更新。

它不减少网络层数、参数量或卷积数学运算量；也不把197个kernel变成一个融合kernel。更紧凑的提交可以减少CPU开销和GPU等待，故GPU事件时间也可能下降，但不能据此说卷积FLOPs下降。

本实现的Graph与TRT执行上下文、形状及缓冲地址关联，首次初始化/资源分配在捕获前完成；每次加载创建自己的图，不做跨进程保存。稳定地址、图外预热及更新输入后Replay的通用要求可核对[PyTorch2.0 CUDA Graph说明](https://docs.pytorch.org/docs/2.0/notes/cuda.html#cuda-graphs)；TRT context的所有权由上表中的实际代码管理。

### 7.5 Shape、时序与缓冲安全

- 稳定输入仍FP32 [2,3,640,640]，稳定输出仍FP32 [2,5,8400]。
- 每次copy当前输入，防止Replay旧画面；左右目始终在同一batch的0/1位置。
- clone让每次返回的raw有独立storage，防止NMS原地改写捕获缓冲、下一批覆盖上批输出。
- wait_stream建立调用流与私有流的先后关系；record_stream防止异步使用期间被allocator过早回收。GPU流等待不是每帧CPU全设备同步。
- 捕获范围只包围TRT enqueue；预处理、输入更新、输出clone、NMS、A2和ROS都在图外。
- 增加一次9.83MB级输入D2D和336KB级输出clone，以及私有context/缓冲常驻成本；不是没有代价的加速。

### 7.6 为什么可能更快

减少反复launch/提交的主机开销，缩短GPU工作之间的提交空洞。当CPU/提交开销占比高时有机会受益；如果几乎全是连续长kernel，收益可能很小。输入更新、输出clone和同步必须算进真实收益，不能只测一个graph.replay()返回要多久。

### 7.7 三层实测证据，分别解释

**第一层：E03单轮trtexec诊断。** 新E01 performance Engine、常驻输入、25W/408MHz，每种情况60秒、2秒预热、至少1000次。普通→Graph：GPU Compute 28.5369→26.4055ms，enqueue 2.72675→0.101161ms。这是单轮诊断，不是生产系统成绩，也不能把96.3%的enqueue下降说成系统快96.3%。

**第二层：E04 phase2实际Graph forward。** 三轮完整forward CUDA事件对照约29.670→27.934、29.554→27.979、29.518→28.007ms；平均29.581→27.973ms。这里包含输入更新/输出clone，边界不同于阶段0纯Engine的28.136ms。来源：[Graph实机补记](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/AGENT_B_REPORT.md)。

**第三层：E04 phase5组合在同场景系统里的增量。**

| 指标，25W/408MHz | A2 | A2+Graph（R4） |
| --- | ---: | ---: |
| 固定图检测器均值 | 56.074ms | 54.633ms |
| 有球系统检测器均值 | 58.739ms | 56.694ms |
| cycle均值 | 66.058ms | 63.973ms |
| processing Hz | 15.100 | 15.590 |
| 读取完成至发布均值 | 61.548ms | 59.491ms |
| 同范围P95 / P99 | 65.131 / 71.022ms | 62.307 / 67.033ms |

R4相对同期A2的三轮Hz增量为+3.336%/+3.023%/+3.380%，宏平均+3.246%；read-ready平均再省2.057ms。R4相对R0的配对宏平均为+6.928%、平均read-ready节省4.454ms，不是把A2和Graph的百分比直接相加。

该轮100预热、60秒、每scope三轮首尾R0交错；system有效窗口采样全408MHz。phase5没有重测组合的纯Engine事件，不能给R4再填一个“实测Engine=26.406ms”。约0.89ms的inference方法墙钟是异步提交，不是完成时间。

R4仍出现第3轮read-ready最大87.609ms、cycle最大92.391ms，不能说已消除卡顿。只有三次独立重复，数万帧不等于数万次独立实验；B5长期稳定性没有完成。[性能与局限](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/PERFORMANCE_COMPARISON.md)

### 7.8 输出、精度与定位

同一Engine、相同输入与执行计算，设计上保留输出语义；不能跳过正确性检查。E04验证固定和变化输入，单项及组合Golden一致，Graph有效作业capture=1、update/replay/clone计数匹配、零fallback，恢复完整。

61对Val实现等价不等于全量AP或物理三维误差验收。现场R4的测量有效率98.860%，R0为99.429%，输入不是逐像素相同，不能据此认定Graph导致精度退化，也不能宣称物理精度已完全通过。coasting下跟踪有效也不等于有新的三角化测量。

### 7.9 当前部署、启动和换模型

**正常启动路径已接入，YAML默认a2_graph。** 每次启动/重新加载时自动捕获一次，模型不变也一样；build_project.sh不捕获，进程退出后图不保留。捕获失败时effective=b0及fallback原因可见。

成功状态应包含engine.effective=graph、capture_count=1、fallback_count=0，后续replay_count随调用增加。仅有enabled=true或配置名称不足以证明成功。

当前实现严格适配静态TRT8.x和当前I/O。如果新模型保持兼容接口，会在加载时重新捕获；多类别、不同shape、TRT10/11或不同输出不能只换路径就保证支持。重新构建Engine与重新捕获Graph是两件事。

### 7.10 面试追问

- “会一直检测上一帧吗？”——每次Replay前明确copy本批输入，变化输入实机对照验证过。
- “为什么必须clone？”——输出缓冲地址固定且复用，后处理或下一帧可能覆盖；clone换取独立结果所有权。
- “Graph捕获整个感知系统吗？”——没有，只捕获TRT执行；动态NMS、CPU回传和ROS都在图外。
- “收益是不是GPU运算量减少？”——不是，主要是提交/执行空隙改善；实际系统增量必须A/B。
- “构建时捕获后保存行不行？”——当前实现不能跨进程复用上下文和地址，运行进程每次重新捕获。

## 8. MAXN：改变硬件运行条件，不能与25W数据混算

### 8.1 原流程和约束

E03/E04正式性能是在本机25W、mode3、GPU上限408MHz、动态时钟下得到的。CPU/EMC也受模式与调频策略影响。25W是配置档位，不是实验期间测得整机恒定消耗25W。

### 8.2 后来的流程

10月23日后续调查记录设备已有MAXN mode0，GPU动态范围306～918MHz；E01 Engine hash、A2/Graph及检测/定位配置保留。改变的是硬件允许的资源和频率范围，没有因此改网络、重训练或重新选择Engine内部tactic。

记录没有给出谁在何时用哪条命令切换模式，本文不补造一份“Agent已执行切换”的历史。

### 8.3 真实代码、配置和证据位置

MAXN属于系统配置，**没有对应的YOLO模型修改函数**。NV power model通常由/etc/nvpmodel.conf及系统工具管理，不应编造一个项目中的MAXN优化kernel。

- [audit_robot.main相关代码](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/audit_robot.py:144)：第147行只读nvpmodel -q；第154–159行读GPU sysfs频率、负载和温度。
- [run_performance_robot的功耗门禁](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/run_performance_robot.py:156)：原25W实验核对模式，不自动切换。
- [MAXN后续报告](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/preprocess_race/20261023T014627Z/REPORT.md)：记录mode0、动态306～918MHz及新轮尚无性能结论。
- 当前build/run脚本没有自动切功耗或锁频；本文未执行nvpmodel、jetson_clocks或写sysfs。

### 8.4 原理

功耗模式规定可启用资源和频率上限；DVFS根据负载、功耗和热条件动态选实际频率。MAXN扩大部分运行空间，CPU/GPU相关任务可能更快；仍受供电、散热和其他瓶颈限制。

**MAXN与jetson_clocks不同**：前者选择资源/功耗模式，后者用于设置模式允许范围内的静态最大频率。不能看到MAXN就写成“GPU始终锁在918MHz”，也不能称MAXN为固定某个瓦数。[Jetson Linux R35.6.0官方说明](https://docs.nvidia.com/jetson/archives/r35.6.0/DeveloperGuide/SD/PlatformPowerAndPerformance/JetsonOrinNanoSeriesJetsonOrinNxSeriesAndJetsonAgxOrinSeries.html)

模式ID/上限与具体BSP、设备及配置有关。本文408/918来自本项目记录，不推广为所有Jetson的固定对应关系。

### 8.5 数据流与Shape

完全相同：图像→FP32 [2,3,640,640]→同一Engine→FP32 [2,5,8400]→原NMS+A2→定位/ROS。改变执行这些工作的硬件频率/资源，不改变Tensor shape或图算法。

### 8.6 为什么理论上可能更快

同一GPU计算任务在其他条件相同时，提高频率可能缩短计算时间；CPU处理也可能受益。但918/408=2.25只是一项频率上限比，不能直接预测2.25倍FPS。等待、CPU、内存、采集和输出占比并不都按GPU频率缩放，MAXN同时还可能改变CPU资源。

### 8.7 真实结果与局限

| 条件 | 有什么证据 | 能得出什么 |
| --- | --- | --- |
| 25W、上限408MHz | E03与E04多轮原始CSV、遥测、配对审查 | 可以在对应phase内部讨论A2/Graph收益 |
| 后来的MAXN、动态306～918MHz | 已有只读调查与源/安装一致记录 | 可以确认当时的硬件模式及软件身份 |
| MAXN约23Hz | 后续报告转述用户观察，未正式复测 | 只能称观察值，不能当受控实验均值 |
| 25W vs MAXN同条件三轮A/B | 未完成/未提供 | **MAXN独立收益尚未量化** |

不能写“E04代码把14.580Hz提高到23Hz”，也不能将MAXN观察值与E03约17Hz相除后宣称某优化百分比。新的canvas/reuse筛选还待采集，不能拿计划里的400次、3组系统测试当成已运行。

后续只读报告还说明部分EMC sysfs查询权限不足；不能将缺失读数当作已知内存频率、零活动或已确认的带宽瓶颈。

### 8.8 输出、精度和协议

功耗模式本身不改变模型数学定义、类别或协议，不属于量化。它可以改变实际处理/采样节奏与热态，故真实系统表现仍需同场景验证。没有一份MAXN模式下新增的全量AP或物理定位验收。

### 8.9 当前部署状态

**最新已有实机调查记录为MAXN；由外部系统配置管理。** 它不是E04原25W正式实验的一部分。本次未进行实时设备查询，不将历史状态冒充此刻遥测。

### 8.10 面试追问

- “提速主要来自代码还是功耗？”——25W下A2/Graph有同条件配对证据；MAXN独立贡献尚无受控A/B，不能混合归因。
- “MAXN是不是锁频/固定瓦数？”——都不是；要分开报告模式、实际频率和功耗遥测。
- “切MAXN后会重新优化Engine吗？”——当前只是同一Engine运行条件变化，没有自动重新构建或重新挑选tactic。

## 9. E02 C3k2缩窄：参数少了，实际执行组合反而更贵

### 9.1 原实现和修改动机

E01全局第19层C3k2的hidden expansion为0.5，内部隐藏通道128。希望通过减少内部卷积宽度降低算术和访存成本；它当时是范围较小的实验切入点，并未先证明是最值得改的瓶颈。

### 9.2 修改后的流程

仅将e改成0.4375，hidden128→112，外部接口不变。用分支感知前缀映射同步迁移split/concat/残差与BN参数，再恢复训练；不是只改YAML就直接测随机模型，也不是L1重要性剪枝。

### 9.3 真实源码

- [architecture.yaml第39行](/home/misaka/workspace/experiments/E02_c3k2/architecture.yaml:39)：第19层为C3k2 [512,true,0.4375]。
- [transfer_layer19](/home/misaka/workspace/experiments/E02_c3k2/migrate.py:21)：第26行限制外部in/out不变；39–48行同步卷积和BN参数；55–71行处理各分支通道映射。
- [transfer_model](/home/misaka/workspace/experiments/E02_c3k2/migrate.py:75)：第81行只允许model.19内部shape变化，其余状态逐值复制。
- [E03逐层配对](/home/misaka/workspace/experiments/E03_tensorrt_profiling/results/L19_layer_pairs.csv)及[L19汇总](/home/misaka/workspace/experiments/E03_tensorrt_profiling/results/l19_comparison.csv)：实际TensorRT执行证据。

### 9.4 原理：FLOPs不是延迟模型

卷积理论工作量与通道数相关，但实际延迟还取决于kernel/tactic、块大小、向量化、访存布局、融合和复制。更小shape可能选中不同实现，未必更快；全网只改变很小一部分时，端到端收益上限也很低。

### 9.5 Shape与模型规模

~~~text
L19外部输入：[B,384,40,40] → 外部输出：[B,256,40,40]，两者不变
隐藏通道：128 → 112
新detailed图内一个cv1卷积：[2,64,40,40]→同shape
                       变为：[2,56,40,40]→同shape
全网参数：9,948,638 → 9,881,630，减少67,008，约0.674%
最终raw仍为：[2,5,8400]
~~~

内部减少12.5%通道，不等于整网减少12.5%成本；更不等于系统快12.5%。

### 9.6 理论收益上限与实际阻碍

L19只占旧E01逐层profile合计4.80%。串行近似下，局部耗时减半只对应总profile约2.40%；完全消除也只约4.80%。这是局部上界分析，分母是带profiler影响的执行合计，不是对正常系统Hz的收益承诺。

E03已观察到tactic变化和新增Copy。112、56都满足所见的channel%8约束，不能草率说“112不对齐Tensor Core，所以变慢”。具体kernel利用率、带宽瓶颈或各因素因果占比没有硬件计数器/强制tactic A/B支持，不能伪装成已证明。

### 9.7 真实结果、条件和归因

原Engine，25W/408MHz、100预热、每轮60秒、三轮交错：

| 指标 | E01 | E02 |
| --- | ---: | ---: |
| 正常Engine事件均值 | 28.13498ms | 28.27537ms |
| L19核心执行，三次profile均值 | 1.18682ms | 1.21988ms |
| L19辅助执行 | 0.18169ms | 0.25944ms |
| L19合计 | 1.36850ms | 1.47933ms |

E02整Engine未加速；L19合计反而+0.11083ms、+8.10%。局部增量约70.2%来自辅助执行增长；额外Add输出Copy约0.06159ms，占局部增长约55.6%。

新performance对照为28.17795/28.22171ms，差仅0.04377ms且逐轮方向不完全一致，也不能证明收益。新detailed内部cv1为0.09522→0.11269ms，并选择不同tactic；这些tactic只属于新detailed图，不能代填旧Engine缺失元数据。

结论是“当前设备、构建和shape下形成了更差的实际执行组合”，不是所有缩窄都无效，也不是已证明单一根因为通道对齐。[E03完整解释](/home/misaka/workspace/experiments/E03_tensorrt_profiling/REPORT.md)

### 9.8 精度、输出和定位

结构/权重改变，不能保证原始输出相同。恢复训练实际78轮、最佳epoch48；Val mAP50 E01/E02为96.0161%/95.9545%，mAP50–95为78.5508%/78.7770%。整体接近，不是精度完全不变。

E01历史评估CPU、E02评估CUDA，是相同数据/指标的跨设备历史对照。缺少同预算E01继续训练control结果，微小AP差异不能完全归因于缩窄。外部检测/定位协议不变不代表三维数值逐位一致。[E01/E02报告](/home/misaka/workspace/benchmarks/E01_E02_REPORT.md)

### 9.9 当前部署状态

**已尝试，未取得加速，不作为当前主部署模型；当前使用E01。** 不继续无依据搜索L19宽度，也不把E02的0.674%参数减少写成实时性能提升。

### 9.10 面试追问

- “参数下降为什么不更快？”——参数是容量指标；真实成本由shape、tactic、布局和辅助执行决定，本次局部Copy与核心执行都变贵。
- “那下一层该改哪里？”——E03显示Backbone约37.99%、Neck约21.41%、辅助约16.05%、Attention块约10.39%；先用目标设备热点定位，不能只按模块名或FLOPs排名。
- “为什么不先删Attention？”——层名可识别MatMul/Softmax只约5.31%，证据不支持把Attention当整网第一成本。

## 10. 已尝试但未默认采用：逐项说明

下面的“不采用”不全等于“完全没有收益”：有的是局部收益太小/系统增量不稳定，有的是兼容性或正确性门槛未通过，还有的是根本只有探针、尚未实机测量。

### 10.1 A1：CPU候选构造简化

| 核对项 | 具体解释 |
| --- | --- |
| 1. 原流程/问题 | 已回CPU的NumPy数组逐标量拆箱、重复查询名字并构造BallDetection；Python小操作有成本 |
| 2. 修改流程 | 一次tolist转为Python数值，再批量循环构造；保留三次/目转换、原稳定排序和末尾top-k |
| 3. 真实代码 | [PostprocessHandle._convert，第88–114行](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/postprocess.py:88) |
| 4. 原理 | 减少解释器层的小对象/查找开销，属于CPU结果构造优化 |
| 5. 数据流/Shape | 仍为各目[N,6]→相同候选列表，没有减少模型Tensor维度 |
| 6. 理论收益 | 只作用于较小的CPU片段，GPU等待及NMS等主要成本仍在 |
| 7. 实验/限制 | E04 phase3 A1为14.914Hz，R0为14.861Hz，报告判定无稳定收益；A1+A2为15.494Hz，还低于同期仅A2的15.572Hz。条件为该阶段25W/408MHz、有球、三轮100预热/60秒，不挪用到phase5 |
| 8. 输出影响 | 被测候选、顺序及下游语义一致，不能据此声称全场景速度更好 |
| 9. 部署状态 | 有可逆实现，**不在当前a2_graph组合中启用** |
| 10. 面试回答 | “Python微优化做了等价验证，但整链路收益不稳定，因此没有为了代码更短而强行采用。” |

### 10.2 E04 C2：复用host打包缓冲，不重写Resize

| 核对项 | 具体解释 |
| --- | --- |
| 1. 原流程/问题 | 原pre_transform后np.stack，再做RGB/BCHW视图和ascontiguousarray；重复分配及整图打包 |
| 2. 修改流程 | 仍调用原pre_transform；逐目np.copyto到复用uint8 BCHW host缓冲，阻塞to(device)，再float和/255 |
| 3. 真实代码 | [PreprocessHandle._reuse，第112–137行](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/preprocess.py:112)：119–128分配/打包，133–135传输/转换/归一化 |
| 4. 原理 | 减少host临时数组分配和复制；不是GPU插值、不是异步流水线 |
| 5. 数据流/Shape | host为[2,3,640,640] uint8共2,457,600B，只分配一次；返回GPU FP32同shape，每次独立storage |
| 6. 理论收益 | 省掉部分pack开销；Resize/Letterbox和必要传输/数值转换仍保留，不能节省全部约9ms预处理 |
| 7. 实验/限制 | phase5预处理三轮节省0.322/0.382/0.362ms；R5对R4系统Hz增量+1.610%/−0.218%/+0.911%，宏+0.768%。第2轮read-ready均值慢0.183ms、P95慢0.374ms。局部节省可重复，系统增量非三轮全胜 |
| 8. 输出影响 | 该轮61对Val和R5组合等价通过；阻塞传输保证host可安全复用，FP32输出独立，不覆盖旧输出 |
| 9. 部署状态 | 代码存在，**当前生产映射preprocess=c0，C2不默认启用** |
| 10. 面试回答 | “先减少不必要的CPU复制，但节省只有约0.3～0.4ms；更复杂的缓存不值得在尾部和系统增量未稳定时默认上线。” |

R5总体池化15.710Hz高于R4的15.590Hz，不足以推翻三轮增量方向不一致的事实。也不能把这种0.3～0.4ms节省当作达到30/50Hz的解决方案。

另一个真实集成约束：C2会冻结首次成功调用的原图shape。当前生产load使用640×640黑图初始化；若未来把C2直接加入这次启动流程，可能先冻结黑图shape，之后VGA真实图走fallback。当前a2_graph没有启用C2，因此不受此问题影响；后续候选应在load结束后按真实输入初始化，不能未经验证强行叠加。[后续可行性审查](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/preprocess_race/20261023T014627Z/agents/b/feasibility.json)

### 10.3 Torchvision CUDA NMS / E04 A3：兼容性未通过

| 核对项 | 具体解释 |
| --- | --- |
| 1. 原流程/问题 | 纯Torch greedy NMS有Python循环、动态索引和多次GPU小操作；这里“纯Torch”不等于所有数值在CPU执行 |
| 2. 希望的流程 | 使用兼容的编译NMS算子；当前未获得可用并验收的替代实现 |
| 3. 真实代码 | [原nms_fallback，第38–63行](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/adapters/yolo.py:38)；[A3状态，第46–52行](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/postprocess.py:46)；[compiled op probe](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/adapters/nms_backends.py:98) |
| 4. 原理 | 编译实现可减少Python控制和重复小操作，但必须匹配Torch/CUDA/ABI并保留边界和排序语义 |
| 5. Shape | boxes[N,4]、scores[N]→keep[K] int64 indices，算法替代不能改变左右归属 |
| 6. 理论收益 | 可能降低NMS内部开销；收益依候选规模和传输路径，不能用通用宣传数字估计 |
| 7. 实验/限制 | 机器人Torchvision0.15.0扩展报undefined symbol: _ZNK5torch8autograd4Node4nameEv；E04 A3明确effective=a0并计fallback，无有效A3收益可报 |
| 8. 输出影响 | 当前保留原NMS；未来替换还需同分、边界、退化框、数量和定位对照 |
| 9. 部署状态 | **可用CUDA替代未实施/未验收**；未全局升级Torch/Torchvision/CUDA |
| 10. 面试回答 | “先确认实际调用路径和ABI，无法加载的算子没有性能成绩；回退成功也不等于CUDA NMS优化成功。” |

### 10.4 GPU Resize、VPI/VIC、canvas/reuse：区分探针与已上线方案

| 核对项 | 具体解释 |
| --- | --- |
| 1. 原流程/问题 | OpenCV INTER_LINEAR Resize、114 padding及CPU打包仍有成本。E04 C1诊断pre_transform约6.260ms，是该探针八段方法墙钟主要部分 |
| 2. 候选流程 | GPU插值候选希望转移Resize；canvas/reuse则保留OpenCV插值，复用ROI画布/打包。二者不是同一技术 |
| 3. 真实代码 | [机器人冻结BasePredictor.preprocess](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/runs/20261022T020842Z_78f1b7/audit/source/installed/ultralytics_0/engine/predictor.py:150)；[新CandidateHandle._canvas，第76行](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/preprocess_race/20261023T014627Z/tools/candidates.py:76)；[VPI探针源码](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/preprocess_race/20261023T014627Z/tools/vpi_probe.py) |
| 4. 原理 | 改变计算设备可能利用并行性；复用画布减少分配/复制。但H2D、格式转换、同步以及与Engine争用GPU都要计成本 |
| 5. Shape与几何 | 目标仍为640方形、BGR→RGB、左右batch2、FP32/255；需保留缩放比、Python round、padding±0.1、114填充及坐标逆变换 |
| 6. 理论收益 | 减少Resize或周边内存工作；只有全链路同步完成计时才知道收益，单个Resize kernel快不等于系统快 |
| 7. 实验/限制 | 旧CPU数值筛查：Torch bilinear+round对64张真实图和1张随机图，44,678,400通道像素中4,729,766个不同，约10.59%，最大差1 uint8。不是GPU测速。新MAXN canvas/reuse只有开发/CPU检查，实机正确性/性能待采集；VPI2.4.8可import也不等于CUDA/VIC支持及收益已验证 |
| 8. 输出影响 | 1灰阶差异经/255约为0.00392，可能影响分数阈值、小目标、NMS及双目匹配；必须追到检测/定位，不能只凭肉眼看图 |
| 9. 部署状态 | **GPU Resize/VPI/VIC未用于当前生产；canvas/reuse未上线**；当前仍原预处理c0 |
| 10. 面试回答 | “不同库的bilinear不保证uint8舍入一致；发现数值不等价后没有偷偷接受，保留原OpenCV并把新候选单独验证。” |

上述10.59%不代表10.59%的检测错误，也不能据此断言GPU插值一定不能用；它仅说明当前探针不满足精确等价门槛。原始来源：[旧预处理报告](/home/misaka/soccer_backend_tensorrt/experiments/E02_trt_realtime_p1_p4/AGENT_C_REPORT.md)，当前状态以[MAXN调查报告](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/preprocess_race/20261023T014627Z/REPORT.md)为准。

### 10.5 容易混淆的早期工程实验：NumPy NMS与single_class快路径

部署仓库的experiments/E02_trt_realtime_p1_p4是一个**早期工程实验目录**，不是本文第9节的E02_c3k2结构缩窄。当前源码保留其可选模块，不等于当前a2_graph启用了它。

| 核对项 | 具体解释 |
| --- | --- |
| 1. 原流程/问题 | 旧后处理通用分支及Torch greedy循环存在额外控制成本 |
| 2. 修改流程 | single_class路径精简普通单类整理；可选NumPy NMS在原device先按旧规则排序，排序后的boxes回CPU，CPU greedy IoU，再把保留indices传回原device |
| 3. 真实代码 | [single_class_nms](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/adapters/fast_postprocess.py:31)、[make_fast_predictor_class](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/adapters/fast_postprocess.py:142)、[numpy_nms](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/adapters/nms_backends.py:41)、[旧开关选择](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/adapters/optimization.py:12) |
| 4. 原理 | 用CPU向量计算替代小规模GPU循环，但增加D2H/H2D；保留原device排序以减少同分选择变化 |
| 5. 数据流/Shape | [N,4] boxes+[N] scores→CPU选框→原device[K] indices；single_class还返回FastDetectionResult，接口不同于A2浅拷贝Results |
| 6. 理论收益 | 小候选集CPU算得快的收益可能被传输和同步抵消，不能只看NMS函数本体 |
| 7. 真实结果/限制 | 旧25W、Viser开启、30秒短组，NumPy NMS单项两轮完整系统13.717Hz，原始13.503Hz；旧ABC三轮15.431Hz，180秒15.298Hz，仍未达20Hz。这些是另一套历史实验条件，不并入E04三轮60秒数据，也不是MAXN数据 |
| 8. 输出影响 | 历史实机样本和同分边界对照通过，不能推出所有设备/任意框都等价；没有取消NMS |
| 9. 部署状态 | 有代码和历史验证，**默认关闭；当前a2_graph会拒绝非默认旧predictor变量叠加** |
| 10. 面试回答 | “保留负面和小幅收益：微基准有改善不代表整链路足够大；当前选A2+Graph，是有清楚同条件证据和接口边界的路线。” |

来源：[早期性能报告](/home/misaka/soccer_backend_tensorrt/experiments/E02_trt_realtime_p1_p4/PERFORMANCE_COMPARISON.md)。不要把早期约14.28%的ABC提升写成E04 A2+Graph的收益，也不要把那次180秒观察写成E04 B5长期稳定性通过。

## 11. 尚未实施或未正式采用的方向：明确留白

| 方向 | 当前状态 | 可能减少什么 | 为什么不能写成已有成果 |
| --- | --- | --- | --- |
| INT8 PTQ/QAT | **当前未实施** | 部分卷积/矩阵的计算和访存 | 没有当前Engine校准/量化、Val小球/遮挡精度和Orin正式A/B；存在库函数不代表本项目使用 |
| FP16外部I/O | **当前未实施** | 输入/输出存储和传输/转换 | 当前binding明确FP32，Graph也校验FP32；需独立Engine及消费者适配 |
| 将NMS集成进TRT/EfficientNMS | **当前未实施，仅兼容性研究** | 外部后处理、交接和部分框架开销 | 会改变Engine输出binding及可能的候选上限/边界，需要重建和Golden；现有Engine不变 |
| 删除NMS / 换one-to-one导出 | **当前未实施，不能直接取消** | NMS成本 | 当前one-to-many有重复预测；旧96张有球数据960→96框，实际去掉864重复候选，不能靠模型名称推断免NMS |
| 512/416输入、YOLO26n | **当前未实施** | 模型计算/特征图大小 | 小球精度、定位误差及输出shape均需独立验证；当前保留640 |
| 高分辨率Backbone/Neck结构调整 | **当前未实施** | E03测得的前段Conv、融合/Copy热点 | 只有热点证据，没有新的训练、Val和目标Engine结果 |
| 删除/缩窄Attention | **当前未实施** | 某些矩阵与块内计算 | 现有证据不足以列第一优先级；不能从名字断言瓶颈 |
| 异步采集/预处理/推理重叠 | **当前未实施** | 串行等待 | 需要队列长度、图像年龄、丢帧、P95/P99；吞吐高可能延迟更大 |
| 双缓冲 / pinned异步H2D / 零拷贝 | **当前未实施** | 传输/等待 | 现有A2/C2阻塞传输，Graph输入copy不是跨帧双缓冲；需新增明确所有权与同步验收 |
| 单目检测+右目对应搜索 | **当前未实施** | 第二目网络执行 | 当前selector需要两目YOLO候选，需开发可靠对应与深度误差验证，不能直接删右目 |
| 25W/MAXN受控功耗A/B | **尚无正式配对结果** | 识别硬件档位贡献 | 已观察MAXN不等于已完成档位因果实验；本文不运行 |
| B5长时间内存/稳定性 | **未完成** | 不是加速技术，而是部署验收 | 短测零回退、计数正常或180秒历史观察不能证明长期无泄漏 |

以上只整理研究边界，不构成继续执行优化/实验的计划或授权。

## 12. 把已有结果放回各自口径

### 12.1 可以引用的成绩

| 数据 | 数值 | 必须随数值说明的范围 |
| --- | --- | --- |
| E01 Val mAP50 / mAP50–95 | 96.0161% / 78.5508% | 既有1223张Val，非Test；历史评估口径见E01/E02汇总 |
| E02参数下降 | 0.674% | 不是FLOPs或延迟下降；实机没有加速 |
| E03原E01 Engine | 28.135ms/batch2 | 25W、上限408MHz、常驻输入、三轮60秒 |
| E03现场锚点 | 16.812Hz | 单轮30秒、Viser开启；不是E04同期基线 |
| E04阶段0系统 | 18.610Hz | 冻结配置、Viser关闭，场景与后续有球测试不同 |
| E04 phase5 R0→A2 | 14.580→15.100Hz | 同期有球系统，三轮配对宏平均+3.566% |
| E04 phase5 R0→A2+Graph | 14.580→15.590Hz | 同期25W/408MHz，三轮配对宏平均+6.928% |
| E04 phase5 A2→A2+Graph | 15.100→15.590Hz | 用于识别Graph增量，配对宏平均+3.246% |
| MAXN约23Hz | 用户观察值 | 正式新轮A/B未采，不填mean/P95，也不与上述值计算代码收益 |

phase5绝对值按原始帧池化；processing Hz按有效窗口计数/时长；相对收益按每轮候选相对首尾R0指标平均，再三轮等权宏平均。直接用表中15.590/14.580−1不等于6.928%，不是算错，而是统计口径不同。

phase5完整原始审查：[combined_numeric_review.json](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/runs/20261022T020842Z_78f1b7/phase5_combo_performance_20261022T090140Z_4d6d9a/combined_numeric_review.json)；归档索引：[RAW_DATA_INDEX.md](/home/misaka/workspace/experiments/E04_tensorrt_pipeline/RAW_DATA_INDEX.md)。索引保留了历次“待运行”交接文字，必须沿时间顺序读到对应回收段，不能只看开头。

### 12.2 约17Hz与后来的15.590Hz并不矛盾

原约17Hz的系统记录有效；不同阶段画面、候选/跟踪负载、Viser、背景负载、热态和观测工具不完全相同。不能拿历史17Hz与另一场景优化后的15.590Hz直接比较，也不能把有球优化收益外推到空检测帧。公平结论来自同phase交错A/B。

### 12.3 为什么还不能承诺30/50Hz

30Hz的串行周期预算约33.33ms，50Hz约20ms。在E03的25W条件下，纯Engine约28.135ms已经高于50Hz预算，其余工作也要花时间。A2和Graph有证据改善链路，但不意味着单靠这两项就达到目标。MAXN下须重新测各边界，不能搬用25W预算宣称已达标。

发布上限也会影响观察：10月22日机器人配置上限50Hz，本地配置15Hz，两端故意未整目录覆盖。上限不是实际处理能力；相机配置100fps、batch2也不意味着100Hz或将帧对Hz乘2。

## 13. 在论文中可以怎样准确写

可以采用以下写法，随后引用本项目原始表：

> 本研究以足球单类别YOLO26s为感知基线，在Jetson Orin NX上复用固定batch2、640输入、FP32外部I/O的TensorRT Engine，内部允许FP16执行策略。针对双目结果交接开销，在保留原置信度过滤、NMS、坐标恢复及候选排序规则的条件下，将两目最终检测结果合并为一次CPU回传；针对重复GPU工作提交，使用独立TensorRT执行上下文和稳定GPU缓冲捕获CUDA Graph，每次执行前更新本批输入，并为返回输出保留独立存储。在25W、GPU上限408MHz的固定相机有球场景中，三轮交错对照得到处理频率14.580→15.590帧对/秒，配对宏平均提升6.928%，读取完成至发布均值配对节省4.454ms。实现等价性在固定Val样本中验证，长期稳定性、全量精度及物理定位误差不由该短时实验结论覆盖。

随后单独写：

> 后续设备运行于MAXN模式，已有约23Hz现场观察；由于缺少与25W的同条件受控对照，该观察不用于量化软件优化或功耗模式的独立贡献。

避免以下写法：

- “用FP16把全系统精度都降成16位，速度翻倍”——外部仍FP32，也无此独立收益数据。
- “E04通过Conv-BN融合又节省Xms”——没有该单项A/B，部署图已有融合。
- “A2在CPU对8400框做NMS”——回传位置、数据量和算法都说错。
- “CUDA Graph只需运行一次网络，以后复用预测”——每帧仍执行模型，更新输入。
- “28ms降到0.9ms”——把GPU完成与异步提交墙钟混为一谈。
- “MAXN使算法加速到23Hz”——没有隔离硬件模式和软件贡献。
- “E02减参说明剪枝成功实现实时加速”——结构迁移流程成功，速度目标失败。
- “Golden全等说明真实三维精度无损、系统永久不泄漏”——证明范围不支持。

## 14. 快速查代码：按业务调用顺序读

1. [detector.yaml](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/config/detector.yaml:6)：E01、conf、class、640、batch2、a2_graph。
2. [PipelineFactory创建检测器](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/pipeline.py:319)：将配置传入适配器。
3. [YoloBallDetector.load](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/adapters/yolo.py:149)：加载、启动初始化、安装优化。
4. [Graph.run](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/graph.py:117)：当前输入更新、Replay、输出clone、流等待。
5. [A2 pack](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/optimizations/postprocess.py:116)：原predict后合并最终框。
6. [候选转换](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/adapters/yolo.py:358)：CPU结果转BallDetection、稳定排序和top-k。
7. [StereoTriangulator.triangulate_camera](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/core/geometry.py:25)：视差d=u_left−u_right，Z=fx×baseline/d；之后转camera FLU。优化保留它，而不是重写定位。
8. [build_ball_position_camera_payload](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/ros/output.py:18)：type、timestamp、valid、confidence、x_m、y_m、z_m七字段保持；坐标单位米，x前/y左/z上。
9. [退出清理](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/soccer_perception/pipeline.py:101)：关闭输入、撤销检测器优化、关闭可视化。
10. [重载回归](/home/misaka/soccer_backend_tensorrt/soccer_perception_ros/tests/test_e04_runtime.py:206)：相同/不同Engine连续load均重建；旧清理失败阻止替换。它是CPU/mock测试，不能冒充CUDA实测。

文档引用的是当前本地源码；历史实验的实际来源由各run manifest、Engine hash和冻结源码标识，不能仅用仓库HEAD替代带未提交改动的源码身份。

## 15. 向技术主管讲述的简明稿

> 我们先建立了足球单类别YOLO26s基线。E01通过兼容权重迁移和微调，明显改善了Val上的检出能力；这部分是模型质量工作，没有直接声称机器人速度提升。
>
> 部署时在Orin NX上使用固定640、双目batch2的TensorRT Engine，内部允许FP16策略，外部输入输出仍为FP32。Conv-BN折叠属于已有推理工具链，后续工程优化没有重新训练或改写这个Engine。
>
> E02尝试缩窄第19层C3k2，参数少了约0.674%，但实机没变快。E03逐层分析发现，该层只占约4.8%，缩窄后实际tactic与辅助复制组合更差，局部耗时反而上升。这说明结构实验必须由目标硬件执行结果来指导。
>
> E03还发现完整检测器存在明显的提交、预处理和结果交接成本。因此E04优先改链路：A2保留原NMS，把左右目最终框合并为一次CPU回传；CUDA Graph为同一个Engine预先记录执行安排，每次更新本批输入后Replay，并用独立输出存储保证后处理安全。
>
> 在25W、GPU上限408MHz的同场景三轮交错实验中，A2+Graph把处理频率从14.580提高到15.590帧对每秒，配对宏平均约6.93%，读取完成至发布配对平均少4.454ms。固定Val的输出和下游协议做了等价核对，但没有把短测说成长期稳定性或物理定位精度全面验收。
>
> 当前E01+A2+Graph已经接入默认启动路径，每次运行在正式推理前重新捕获，构建脚本不捕获。预处理缓存只有局部小收益、系统增量不稳定，未默认采用；GPU Resize、INT8、异步流水线和双缓冲也没有写成已有成果。
>
> 后来设备处于MAXN，约23Hz是现场观察，不能与25W实验混算成代码收益。我们现在能清楚区分模型质量、Engine计算、GPU提交、CPU/GPU交接和硬件频率各自做了什么，也知道每项结论的证据边界。
