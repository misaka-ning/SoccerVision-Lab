# 足球检测模型评估

- 模型：`/home/misaka/workspace/baseline/original_best.pt`；模型类别 `32` 映射为 `0=football`。
- 集合：**val**，1223张；有球813张、确认无球410张，GT球框855个。
- 数据选择：只纳入双项已审核、有效label、状态为reviewed_annotation/negative_confirmed的图片；跳过0张。
- 输入尺寸640，候选置信度下限0.001，固定工作阈值0.25，工作指标匹配IoU=0.5，NMS IoU=0.7，max_det=300。
- Ultralytics 8.4.173；预测采用rect=False的正方形letterbox，不启用TTA。

| 指标 | 数值 |
| --- | ---: |
| mAP50 | 0.6023 |
| mAP75 | 0.5927 |
| mAP50_95 | 0.5541 |
| precision | 0.9946 |
| recall | 0.4339 |
| F1 | 0.6042 |
| no_ball_false_positive_rate | 0.0000 |
| fp_boxes_per_image | 0.0016 |
| positive_image_miss_rate | 0.5437 |

固定工作阈值：TP=371，FP=2，FN=484。无球误报为0/410张，Wilson 95%区间：[0.0, 0.009282440748302413]。

## 口径

mAP使用全部保留候选、IoU=0.50:0.05:0.95、Ultralytics默认最高IoU一对一匹配及官方ap_per_class/101点插值。单类时mAP就是football AP；这不是含COCO面积分层/crowd规则的完整COCO评测。置信度候选下限会截断极低分召回，须在模型间保持一致。

Precision、Recall、F1、TP/FP/FN、漏检率与无球FPR均在预先指定的固定工作阈值计算，阈值过滤后重新一对一匹配。置信度曲线也是逐阈值重新匹配。JSON额外保存的ultralytics_max_f1_precision/recall来自AP扫阈值摘要，与固定阈值P/R不是同一口径；不得在Test上用它挑选部署阈值。

无球FPR = 无球图片中至少出现一个超过工作置信度的football框的图片数 / 确认无球图片数。一张图误报多个框，分子只计一次；另输出误报框数和每图误报框数。无负样本时该值为null/N/A，不是0。没有GT球的子集AP与Recall为null/N/A，不把它记成成功或0分。

检测混淆矩阵的背景真负数没有定义，该单元显示N/A；图像存在性混淆矩阵可定义TN，但其中“有球”预测不保证定位正确。四项场景是重叠子集，图中缺指标显示NA，不能相加或取均值代替全量指标。报告里Wilson区间仅为图像独立假设下的描述性区间，相邻帧/左右目相关性可能使区间过窄。

P-R图为AP50精度包络；所有论文图同时导出所选PNG/PDF/SVG，曲线原始数值保存在tables/，方便统一排版。单张图片不计算“mAP”；per_image.csv保存匹配数量与误报/漏检，false_positive_no_ball.csv列出固定工作阈值下的无球误报图片（无误报时只含表头）。

## 图表

- `figures/pr_curve`：png,pdf,svg。
- `figures/confidence_curves`：png,pdf,svg。
- `figures/no_ball_fpr_curve`：png,pdf,svg。
- `figures/ap_vs_iou`：png,pdf,svg。
- `figures/froc_curve`：png,pdf,svg。
- `figures/detection_confusion_matrix`：png,pdf,svg。
- `figures/image_presence_confusion_matrix`：png,pdf,svg。
- `figures/scene_comparison`：png,pdf,svg。

## 复现与运行范围

- 是否全量集合：True。可用集合原有1223张，实际评估1223张。
- 不把当前Val结果写作Test；部署阈值应在独立Val确定，再固定到Test。
- 原图、label、dataset.yaml、metadata及模型SHA256和运行参数见inputs_manifest.json；评估结束已重查输入文件未变。
- predictions.jsonl保留全部候选和GT，可用于后续离线复核；未修改原数据，未生成原数据目录下的.cache。
- 运行时间与后台报告速度：`{'predict_wall_seconds': 238.0811782980163, 'predict_images_per_second_including_warmup': 5.136903340041098, 'backend_reported_mean_ms': {'preprocess': 1.9602454080873108, 'inference': 187.67305011134263, 'postprocess': 0.3281767491355176}, 'device': 'cpu', 'torch_threads': 1, 'image_loader': 'LoadImagesAndVideos', 'loader_batch_size': 4, 'actual_input_shape': [640, 640], 'backend_fp16': False, 'backend_end2end': False}`。速度含义见metrics.json，包含首次warmup的端到端速度不应直接当作纯推理硬件benchmark。
