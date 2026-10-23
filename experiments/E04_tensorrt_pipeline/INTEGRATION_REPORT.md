# E04 集成与回滚状态（2026-10-22）

单项及R4/R5组合Golden、100个有效性能作业已完成审查。用户已暂停后续实验；候选只在隔离测试路径集成，没有安装进生产，没有长稳或生产采用批准。

## 已实现与审查

三份独立worktree基于真实部署快照b7dab3a1a738c73d3a64614f5aab7b4b1ef328f0，上游部署HEAD为5ef358e9b7df2edcf36d4618d3e2b6aad70e0812并含原有修改。候选源提交e0672063ed58446a9ed3ecec59ad854380f5795b，benchmark参考de01d53744df064d6c551b99cff3b68f5bbd6d20；phase4/source中30份候选源/config/package与phase1逐项相同。phase5来源与工具以performance_manifest SHA304ad65b33cbe5c37f723f0e67e64c64beb70b0237817d0eb5798486b36cfe06为准。

A专有postprocess.py，B专有graph.py，C专有preprocess.py；公共registry和benchmark由协调Agent集成，按B/C/A安装、逆序恢复。默认a0/b0/c0。A2保持原NMS及top-k；Graph稳定I/O、当前输入更新、图外独立输出clone和stream等待；C2保持OpenCV和blocking H2D，仅复用host打包缓冲。未改模型/阈值/网络/尺寸/定位跟踪/ROS协议/生产依赖。

phase1 7变体各61对、phase4 R0/R4/R5各61对Golden均通过。phase5只用30个complete的六个完整5job块；4superseded/1failed不入结论。12个Graph正式作业均capture1、replay/update/clone=100+N、zero fallback、restore完整；C2各作业仅1个host及view分配。CPU工具49项通过，不据此替代B5。

## 测试隔离与实际配置写回

固定E01 Engine副本、640/batch2、conf.45/IoU.7/top-k5，独立ROS87+localhost。保留运控/ROS0和其他后台程序，不调整25W/408MHz上限。实际默认生产配置指向E02，实验显式选E01。

曾因手动预览将两份visualization.yaml置true，导致首个有球启动在配置核验处失败；协调Agent在phase3备份后仅恢复冻结false，两份hash相同。VISUALIZATION_RESTORATION.json与原true备份保留。除此不能误称“配置从未写回”，也不把Viser开关变化算入候选收益。

## 回滚与结论

每个handle.restore()可恢复原实例方法，或完全使用a0/b0/c0/原生产路径；测试退出后独立E01选择和hooks随进程结束。原生产模型/Engine未覆盖，未更换Torch/Torchvision/CUDA、未修改ROS控制逻辑。

R4为当前研究主候选：同期system配对Hz约+6.928%、read-ready省4.454ms，较A2仍有三轮重复增量。R5仅可选诊断，C2系统增量未三轮全部复现。R4现场measurement_valid与R0略有差异，物理定位准确度未验证。B5未跑，不能批准长期部署。用户已暂停后续：不安装生产、不继续测试或自动监视，恢复须用户新指令。
