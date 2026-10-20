# 第2批足球数据集预审记录

> 后续进度（2026-10-16）：用户已确认本批全部审核完成，1000张双项已通过；保留11张“已审核、暂不训练”。详见[批准记录](/home/misaka/workspace/dataset_processing/batch-review-20261016/batch-002-approved/REPORT.md)。下文保留当时预审记录。

日期：2026-10-16。正式数据集：`/home/misaka/workspace/datasets`。

本批使用既有固定名单 `batches/batch-002.txt`，共 **1000张**，从 `frame_005012_left.png` 到 `video_4bec9c343db72928_frame_00000273_right.png`。没有增删图片或调整train/val/test。

## 预审结果

- 实际查看1000张全景及849个现有球框，证据为500页原生全景、108页球框局部对照，另对不确定边界单独放大。四个分组各250张的覆盖记录保存在各组 `summary.json`。
- 调整257张的四项场景值；多标签可同时为1，全部为0表示不属于四类。
- 收紧2份label：`legacy_train_000238.jpg` 原框右侧多余桌面；`legacy_train_009603_L.jpg` 原框上下背景过多。修改后仍为候选标注，原框备份保留。
- 22张标为需要人工修框；9张空label仍无法确定球是否可见，保持No Ball=0并要求核对可见性。
- 209张保留疑点，包含小目标阈值、接触是否遮挡、模糊球缘等问题。完整名单为 `../batches/batch-002-priority.txt`。
- **全部1000张的label和场景两项仍为待用户审核，助手自动通过0张。** 其余图片也需要用户复查。

| 场景 | 图片数（可重叠） |
| --- | ---: |
| 小目标 | 203 |
| 遮挡 | 170 |
| 运动模糊 | 461 |
| 无球候选 | 142 |

## 人工复查

全量固定分组入口（每页50张，共20页，包含全部209张疑点，左右目同帧同组）：

```bash
/home/misaka/workspace/script/review_football_batch.sh 2 --group 1
```

在顶部使用“前50张 / 后50张”翻页；点击图片进入单张编辑，保存后按G返回。场景只显示为1的中文名称，其余留空。需要人工改框和可见性复查的说明保存在每张图片的备注中。

若只想先定位疑点，可使用 `2 --priority --gallery`；这不会替代全量1000张的复查。每张图的预审理由和四项建议也在 [precheck.csv](./precheck.csv)，并可在 [proposals.json](./proposals.json) 找到对应原生证据路径。

## 判定口径

小目标按完整球尺度折算到图像长边672后约40像素判断，约38至41像素的临界样本保留复查。真实前景覆盖才记遮挡；手鞋仅靠近、接触或画面边界裁切不直接记遮挡。球或相机有方向性拖影才记运动模糊，低分辨率柔化及单独脚部模糊不自动记。无球只依据当前视角可见画面，不根据另一目或相邻帧推测被完全挡住的球。

## 备份与校验

审计目录：[本次应用备份](/home/misaka/workspace/dataset_processing/batch-review-20261016/applied/20261016T062920Z-73b60c42)，包含原始metadata和本批1000份label备份；[独立核验](/home/misaka/workspace/dataset_processing/batch-review-20261016/applied/20261016T062920Z-73b60c42/verification.json)。

批外7398条CSV逐行原字节和换行不变；本批所有原图SHA不变；仅2份label变化，849个框总数保持；split、来源字段、计数和已有备注均保留。按图片/label SHA与所有metadata字段拒绝覆盖后续人工改动，写入期间使用与Qt审核工具相同的QLockFile锁。

Qt6.8.3界面冒烟已在真实1000张名单验证：20页可前进及后退、点图返回保留位置、全0分类留空、已选分类中文显示、浏览不自动通过。报告：[smoke.json](/home/misaka/workspace/dataset_processing/batch-review-20261016/batch-002-fixed-groups-ui/smoke.json)。
