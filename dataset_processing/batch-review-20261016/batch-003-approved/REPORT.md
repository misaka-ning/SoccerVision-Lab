# 第 3 批人工完成审核记录

用户于 2026-10-16 明确确认本批 label 和场景均已审核完成。严格按原始 batch-003.txt 的 1,000 张图片记录完成状态。

- 354 张标为 reviewed_annotation，530 张标为 negative_confirmed。
- 116 张标为 reviewed_excluded（已审核、暂不训练）。原因统计：{'No Ball=0但空label': 107, '原不确定处置保留': 7, 'No Ball=1但非空label': 1, 'label格式或几何问题': 1}。保留用户框、分类和既有处置，不补猜测框或无球结论。
- 所选 1,000 张 label_review_required 和 scene_review_required 均为 0。前两批各 1,000 张双项完成状态保留。
- 图片与 label 均未写入，SHA256 与审核前快照全部一致。四项分类、split、来源信息及原注记均保留。
- 批外 7,398 条 CSV 记录和各行原始换行逐字节未变。

完整备份：before/metadata.csv；逐图证据：approved-records.json；校验：verification.json；排除清单：reviewed-excluded.csv。
