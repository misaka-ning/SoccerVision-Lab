# E02 实验计划

假设：在保持P3生成路径和所有对外连接尺寸的条件下，将第19层C3k2隐藏通道128缩至112，可能减少计算而保留足球检测质量。没有证据表明这一层最冗余、该变体最快或能改善遮挡误检。

## 实验与控制

- 索引从0开始，Backbone11条，head[8]为全局19；只将其参数 `[512,true]` 改为 `[512,true,0.4375]`，scale=s。
- 来源为已训练的E1单类权重，使用分支感知前缀通道映射；固定迁移方法，不引入通道重要性打分、稀疏训练、蒸馏或注意力改动。
- 同环境独立control从同一E1权重继续训练，结构不变；与candidate相同训练预算、数据、seed及模型选择口径。原E1成绩仅历史参考。
- 模块19缩窄后可能影响P4/P5；全部权重均可在恢复训练中更新，所以不能声称训练后P3不受影响。
- 复用E1的100 epochs上限、patience30、batch8、640、AdamW与增强。若调整预算，对两组同时调整并创建新run；首轮seed42，多种子另立运行。

## 本次边界

本次只准备环境与文件：复用E1已有CUDA依赖，创建独占runs、候选/对照init.pt、架构/训练配置快照、Train/Val软链接视图、迁移/环境/指纹记录，以及合成CPU前向预检。训练、loss、backward和optimizer step均未运行；Train/Val图像完整SHA验证延后到用户启动训练。Test图像/标签不访问。

## 完成训练后的比较

1. 官方Val fitness选择best；保留last、best、results.csv与实际参数。不要根据Test选择结构。
2. 统一Val：足球class0、640正方形letterbox、min-conf0.001、conf0.25、match-IoU0.5、NMS-IoU0.7、max_det300；使用既有评估实现。
3. 报mAP50/50–95、P/R/F1、无球误报与样本数、Small/Occluded/Blurred分组；分组可重叠。未训练/评估项记null/not_run。
4. 速度在相同Orin、TensorRT版本、FP16、FP32 I/O、batch2和640条件下独立导出到新文件、校验准确性后实测。参数减少0.67%不能换算为等比例Engine或完整视觉加速。
5. 如需E0初始化的纯结构消融，新增独立recipe并对E1架构按同起点同预算重训，不复用本轮“E1恢复训练”结果名义。

## 可复现与保护

prepare独占创建run，失败记录保留，不覆盖已有run；候选与control独立缓存、优化器和输出。记录源权重SHA、架构、脚本、训练参数、冻结manifest、环境版本、初始化映射与前向结果。运行时source/配置变化需新prepare；训练前复核Train/Val内容。冻结数据、原权重和E00/E01均保持原样。

参考：[Ultralytics C3k2模块说明](https://docs.ultralytics.com/reference/nn/modules/block/#ultralytics.nn.modules.block.C3k2)。执行行为以本机8.4.173实际源码为准；该版本双训练分支由one2one分支是否存在决定，end2end标志只选择推理分支，仍保留one-to-many+NMS评价口径。
