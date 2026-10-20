# 第 2 批人工完成审核记录

用户于 2026-10-16 明确确认本批 label 和场景均已审核完成。严格按原始 batch-002.txt 的 1,000 张图片记录完成状态。

- 847 张标为 reviewed_annotation，142 张标为 negative_confirmed。
- 11 张标为 reviewed_excluded（已审核、暂不训练）：2 张 No Ball=1 但保留非空球框，9 张 No Ball=0 但 label 为空。保留用户框、分类和既有处置，不补猜测框或无球结论。
- 所选 1,000 张 label_review_required 和 scene_review_required 均为 0。
- 图片与 label 均未写入，SHA256 与审核前快照全部一致。四项分类、split、来源信息及原注记均保留。
- 批外 7,398 条 CSV 记录和各行原始换行逐字节未变。

完整备份：before/metadata.csv；逐图证据：approved-records.json；校验：verification.json；排除清单：reviewed-excluded.csv。
