# 第一批人工审核完成记录

日期：2026-10-16（Asia/Hong_Kong）。

依据用户明确确认“这1000张我已经review完毕了，全部标记成已审核，label和场景都审核完了”，按固定 batch-001.txt 对本批1000张完成状态登记。

- 707张：reviewed_annotation，球框与场景均已审核。
- 272张：negative_confirmed，空label且用户分类为No Ball=1。
- 21张：reviewed_excluded，人工复核结束，保留原框与分类，暂不进入训练。
- 本批1000张 label_review_required=0、scene_review_required=0。

21张暂不训练包含19张用户选择的不确定处置、一张空label但未确认无球、另加一张用户框存在约0.64像素越界（frame_003650_right）。frame_001674_right原已在不确定组，原框也有约0.64像素越界。没有夹紧或替换用户标注，也没有把空框转成无球。原处置与技术原因追加到备注。

## 无损与并发验证

- 原生 Qt QLockFile 同时锁定本批1000个label及metadata，备份后原子替换metadata。
- 写入前复查选中记录全部字段以及image/label SHA256；新人工修改会导致拒绝写入。
- 7398条非本批CSV记录的原字节与换行完全保留。
- 本批1000张图片、1000份label的SHA256全部未变；四类分类、split、来源、计数字段及未知字段未变。
- Release与Test已重新编译，数据层48项测试通过。安全脚本fixture验证全字段保护、双SHA、锁冲突零写入、精确保留与过期快照拒绝。

## 工具与导出

已审核排除样本在界面显示“已审核 · 暂不训练”。导出时放入 excluded/reviewed 的 images 与 reference_labels，并单独计数，不进入普通 train/val/test，不算待审核。下一批修改和保存可正常进行。

现有skill旧验证器不支持uncertain或reviewed_excluded状态，且会把被隔离的参考框越界视为训练框错误；该旧验证器未修改。实际训练以审核工具导出的 dataset.yaml 为准。

## 本批暂不训练名单

| 图片 | 原处置 | 说明 |
|---|---|---|
| frame_001471_right.png | temporal_only | 原处置保留，暂不训练 |
| frame_001570_right.png | temporal_only | 原处置保留，暂不训练 |
| frame_001576_left.png | uncertain_bbox | 原处置保留，暂不训练 |
| frame_001605_left.png | uncertain_bbox | 原处置保留，暂不训练 |
| frame_001605_right.png | severe_blur | 原处置保留，暂不训练 |
| frame_001674_right.png | uncertain_bbox | 原框几何越界，保留参考 |
| frame_001677_right.png | uncertain_bbox | 原处置保留，暂不训练 |
| frame_001680_left.png | severe_blur | 原处置保留，暂不训练 |
| frame_001680_right.png | severe_blur | 原处置保留，暂不训练 |
| frame_001919_left.png | severe_occlusion | 原处置保留，暂不训练 |
| frame_001921_left.png | severe_occlusion | 原处置保留，暂不训练 |
| frame_002379_left.png | temporal_only | 原处置保留，暂不训练 |
| frame_002379_right.png | temporal_only | 原处置保留，暂不训练 |
| frame_002387_left.png | fully_occluded | 原处置保留，暂不训练 |
| frame_002387_right.png | fully_occluded | 原处置保留，暂不训练 |
| frame_002396_left.png | uncertain | 原处置保留，暂不训练 |
| frame_002396_right.png | needs_manual_bbox_annotation | 原处置保留，暂不训练 |
| frame_002719_left.png | uncertain_bbox | 原处置保留，暂不训练 |
| frame_003650_right.png | needs_manual_bbox_annotation | 原框几何越界，保留参考 |
| frame_004005_left.png | severe_blur | 原处置保留，暂不训练 |
| frame_004005_right.png | severe_blur | 原处置保留，暂不训练 |

## 文件

- before/metadata.csv：下锁后的原始完整CSV备份。
- before/inventory.json：本批1000张全部原字段及image/label SHA256。
- reviewed-excluded.csv：21张暂不训练清单。
- approved-records.json、result.json、verification.json：审批及验证证据。
