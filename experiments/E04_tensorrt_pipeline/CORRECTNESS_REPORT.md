# E04 正确性记录

当前状态：单项与R4/R5组合Golden通过，100个有效性能作业的runtime/计数/恢复已审查。本轮现场测量/跟踪有效率已有记录，但不等于物理定位精度。B5及生产采用未验收，后续按用户要求暂停。以下保留历次阶段记录，最新补充见文末。

已通过：采集工具 7 项测试；实际部署源码的候选选择、测量/定位、调度、跟踪丢失/恢复等 26 项 CPU 回归；固定图接口冒烟。原 Engine、源码与配置指纹在冒烟前后通过检查。

短测实际参数：conf=0.45、IoU=0.7、classes=[0]、agnostic_nms=false、max_det=300、候选 top-k=5。实际输入与原始输出均为 FP32，分别是 `[2,3,640,640]`、`[2,5,8400]`，NMS 为原 Torch fallback。

已采集的 61 对 Val 冻结了原始预处理张量、Engine 输出、NMS 后框、候选顺序/每目归属、双目选择输入、三维测量、跟踪与七字段 ROS payload。确定性回放时间戳和当前 ZED 内参仅用于实现等价性比较，不充当原始采集时间或物理深度真值。

Golden 有47个空检测目、1对左右不对称、37个有效三维测量，最多每目2个候选；仍需补充样本覆盖，空检测、重叠、多框、边界、小目标、模糊、遮挡及左右不对称场景不能仅按目录标签判定通过；不足时增加隔离的合成单测或适用 Val 样本。A/B/C 必须逐项比较数量、顺序、坐标、置信度、类别、左右归属与定位输出。Graph 另需变化输入检查，GPU Resize 另需量化数值和最终结果差异。

## 首版CPU验收与限制

隔离集成65项CPU回归通过，包括A的61对精确候选、244对真实下游pipeline/3D/跟踪/ROS对照，B的13项CPU/mock，C的12项测试和61对输入、公共registry4项生命周期。另9项采集工具测试通过。CPU模型输出来自冻结张量，不能替代GPU推理或Graph成功证明；CPU与Jetson运行库不同。

下一份脚本对同机input/raw/final_boxes要求逐元素相同，JSON bool/int类型严格保留，浮点语义容差1e-10；Engine/config/内参、effective、零fallback、Graph计数和restore均检查。存在差异必须停下审查，不自动放宽容差或减少候选。详见 NEXT_RUN.md。

## 单项实机正确性验收（2026-10-22）

本轮于香港时间11:46:47完成；492个文件逐项size/SHA校验，427个NPZ与冻结基线文件字节一致（7变体×61对、1708个数组）。去重恢复清单完整保留原路径和hash，没有借用旧输出冒充新采集。

R0、A1、A2、A1+A2、B Graph、C1探针、C2各61对均通过：input/raw/final_boxes逐元素相同，候选顺序/类型、双目选择、3D测量、跟踪及七字段ROS语义比较无差异（浮点检查容差1e-10，bool/int类型严格保留）。Engine hash、FP32 I/O、conf/IoU/classes/max_det/top-k、NMS路径和冻结内参均相同。

Graph独立探针71次通过，包含10次固定重放、61组变化输入、旧输出归属及模拟NMS原地改写检查。检测器实际 capture=1、replay=input_update=161、fallback=0；全部组件restore成功。

A2及A1+A2：161次predict、138批打包、285行、138次D2H/6840字节，符合100warm+61Val的逐项推导。C2：161calls=success，host/view各1次分配，2457600字节，不复用GPU输出。C1/C2同机input/raw最大差为0，之前CPU与GPU 1 ULP差异没有出现在本次同机候选对照中。

A、C子Agent独立重跑对照后同意单项正式性能准入。18原模型、原源码99项及已验证候选payload均未变。详细审查保存在本轮 `phase1_review.json`，恢复索引见 RAW_DATA_INDEX.md。

此验收仅批准单项性能实验。A3仍不可用；A+B、A+B+C、长期稳定性、生产采用和任何加速收益均未批准。正式性能脚本沿用已通过的phase1/source，新增代码只负责计时、观测和调度。

## 离线正式性能期间的复核

28轮CSV/真实runtime/warm与final计数已复核，实际绑定/参数/原NMS一致，全部零fallback、restore完整。Graph独立执行首末raw仍匹配Golden；固定图各目候选恒1/1。此轮不重复全Val正确性采集，不把仅候选数相同写成每帧框数值已逐项重验；完整Val输入/输出和语义等价性依据phase1，且候选源码/Engine/hash始终未变。组合与实地物理定位准确性未因此得到新证明。

## 有球单项审查与组合正确性阶段

有球system各单项仍沿用phase1已验源码与Engine；19079帧99.313%双目候选率仅作性能负载审查，不作为3D精度或检测精度证明。R4/R5源码接口已审查，组合Golden尚未运行，必须与新R0及冻结61Val比全张量/候选/定位/跟踪/协议。R5只诊断，不代表采用。

## phase4组合正确性正式回收（已通过）

1. 实际发现：R0、R4_AB(A2+Graph)、R5_ABC(A2+Graph+C2)各61对Val全部通过。183个NPZ完整文件hash与冻结Golden一致，3×244=732个数组逐项精确；input/raw最大绝对差0。框数、坐标、置信度、类别、顺序、左右目归属、双目选择、3D测量、跟踪和7字段ROS语义均一致，比较容差1e-10；三Agent独立复核一致。
2. 修改文件：新增recover_correctness_robot.py、review_combination.py及CPU测试；生成本phase/combination_review.json、六份independent_reviews及指纹清单，更新本实验报告/索引。已验30份候选源码/config/package不变，phase4原始payload和E01资产不改。
3. 正确性证据：217个回收文件逐项校验；99部署源码/配置、18模型、38payload及189参考指纹无错。R4/R5均capture=1、update=replay=clone=161（100预热+61），zero fallback、restore完整；A2各predict161、D2H138、285行/6840B；R5 C2成功161、host/view各1次、2457600B。记录的是恢复钩子成功，不能推断CUDA allocator缓存全部释放。
4. 性能收益：本轮仅正确性采集，没有正式计时收益。R4/R5在性能表仍填not_run，不将单项提升相加。
5. 不确定性：Golden是实现等价参照，不是物理距离真值或全场景检测精度证明；现场运动、遮挡压力、稠密候选及B5长期内存行为仍有限制。此前现场候选非空比例也不能代替3D有效率。
6. 门槛：passed_for_combination_benchmark，仅准入同期R0/A2/R4/R5矩阵；R5诊断，不批准生产、长稳或E04全任务完成。
7. 下一步：新phase5组合性能，固定Val detector15组+人工有球system15组，均100预热/60秒/三轮首尾R0。新工具40项CPU测试、Python3.8与shell语法通过；机器人CPU-only dry-run ready30、无GPU/相机工作，交接时无活动E04作业。正式长任务由用户启动。


## phase5完整性能路径正确性复核（暂停前快照）

293回收文件、261历史及当前job artifact、99源码/18模型/38候选/10工具/189参考指纹无错；最终35attempt只有30complete纳入。12个Graph作业capture1、warm100、replay/update/clone=N+100、零回退、restore完整；6个C2作业host/view各1次、所有调用success；A2按NMS最终框24B/行核对，固定Val两框48B/batch。新只读packet观察warm100、calls=100+N、字段完整及restore通过；system帧号从100逐帧+1，source读取timestamp严格增，未发现错帧计数。

现场原measurement_valid比例R0/A2/R4/R5为99.429/99.632/98.860/99.682%，tracking_valid为99.772/99.890/99.501/99.823%。它们是可用性，不是物理精度，R4差异保留。相同Val输入/raw/final/候选/双目选择/3D/跟踪/ROS732数组精确等价的结论仍成立；没有新全量AP、物理距离或动态跟踪验收。

同负载后验子集仍支持R4延迟收益，但不能证明所有live输入一致；只算延迟不算子集Hz。仍有稀有尖峰，B5长稳未跑，不能声称长期无泄漏或生产安全。主审combined_numeric_review.json、三个独立FINAL_REVIEW及manifest见phase5。新增CPU审查器9项，顶层工具合计49项通过。后续用户已暂停。
