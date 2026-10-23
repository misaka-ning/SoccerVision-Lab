# E04 CPU复算与证据重现

截至2026-10-22，本轮30个组合性能作业已回收审查，后续实验按用户要求暂停。以下仅本机CPU读数据，不打开相机、不启动GPU/ROS，不提供新的长实验启动指令。

## 原始数据身份

本轮：`phase5_combo_performance_20261022T090140Z_4d6d9a`；原始机器人数据保留，完整本机目录：

```text
/home/misaka/workspace/experiments/E04_tensorrt_pipeline/runs/20261022T020842Z_78f1b7/phase5_combo_performance_20261022T090140Z_4d6d9a/recovered_combined_v1
```

combined_recovery_v1.tar.gz为2390574B，SHA256 3eeb8420148c04de902fa586b91075bc244b7a8e130c05258617e0dddf0d8b00。清单292内容条目+清单自身共293文件，大小/SHA逐项通过；35历史attempt仅30complete进入六个完整块，4superseded和1failed保留且排除。

performance manifest SHA304ad65b33cbe5c37f723f0e67e64c64beb70b0237817d0eb5798486b36cfe06；Engine SHA98c1b6bc703b29874d95db94d9cf51ef5b4a4142a7ca6cf22362a0c616fbf348。源、模型、工具及参考指纹见combined_recovery_v1_integrity.json。已验source仍在同run的phase4/source，性能工具原副本在phase5/scripts；请保留这些目录供审查器校验payload。

## 本轮原始CSV独立重算

```bash
/home/misaka/miniconda3/envs/soccer_perception/bin/python /home/misaka/workspace/experiments/E04_tensorrt_pipeline/review_combined_performance.py --recovered /home/misaka/workspace/experiments/E04_tensorrt_pipeline/runs/20261022T020842Z_78f1b7/phase5_combo_performance_20261022T090140Z_4d6d9a/recovered_combined_v1 --integrity-label combined_recovery_v1
```

现有完整结果为本phase/combined_numeric_review.json，包含job_reviews、blocks、pools、block_comparisons、paired_macro、excluded历史及代码SHA。若加--output，须指定新的不存在的文件，工具拒绝覆盖。

```bash
/home/misaka/miniconda3/envs/soccer_perception/bin/python -m unittest discover -s /home/misaka/workspace/experiments/E04_tensorrt_pipeline -p 'test_*.py'
```

49项工具测试通过，新增9项覆盖完整/半块、resume历史、重复complete、数据篡改、nested packet metrics和回传计数。CPU/mock测试不等于实机B5。

## 组合Golden复算（已有结果，不重新采集）

```bash
/home/misaka/miniconda3/envs/soccer_perception/bin/python /home/misaka/workspace/experiments/E04_tensorrt_pipeline/review_combination.py --run-dir /home/misaka/workspace/experiments/E04_tensorrt_pipeline/runs/20261022T020842Z_78f1b7 --phase-dir /home/misaka/workspace/experiments/E04_tensorrt_pipeline/runs/20261022T020842Z_78f1b7/phase4_combo_correctness_20261022T083338Z_a40d24 --output /tmp/E04_combination_review_recomputed.json
```

原Golden位于collection_v1/stage0_golden_attempt1；去重NPZ恢复依照完整文件SHA，不是只比较数组值。主审及三个独立Agent全部本地CPU复核；没有再做机器人推理。实际物理3D精度、AP、SDK曝光时间、队列及长稳不在这套复算范围。

## 统计与重启边界

池化只含六个完整块的原始行；三轮宏收益等权，对照为同轮首尾R0均值。P95/P99配对用端点分位数平均，与池化分位数分开。frame不是独立重复，不对后验不连续子集计算Hz。

重启前detector三块与重启后system三块独立；遥测先按UTC锁定会话，再按system帧cycle窗口筛选。system897样本均408MHz，50.781～52.625°C；detector无逐帧绝对时间戳，只报告包含启动/预热的整job区间，不冒充测量期。详见phase5/measurement_window_telemetry.json/.csv。

## 暂停与历史

用户当前仅要求写报告，后续B5、补测、生产部署及E05均暂停，没有自动监视。旧首次启动/恢复命令仅存历史，不应重复执行。旧阶段说明已保存phase5/report_history/；此前数据索引和失败原始attempt均保留。主仓库未提交/推送。
