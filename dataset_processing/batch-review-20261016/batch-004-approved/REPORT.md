# 第 4 批人工完成审核独立核验

用户已明确确认本批 label 和场景审核完成。本次从原始用户审核快照、批准前 CSV、批准记录与正式 datasets 独立核验。

- 第 4 批共 1,000 张：725 张 reviewed_annotation、234 张 negative_confirmed、41 张 reviewed_excluded；各图状态由现有 label 与快照处置独立复算一致。
- 批内仅 annotation_status、label_review_required、scene_review_required 与追加 label_review_note 可变化；两项审核标志全部为 0，原注记及四项分类、split、来源字段全部保留。
- 1,000 张图片及 label 的 SHA256 与原始用户审核快照、批准记录全部一致，图片和 label 未写入。
- 批外 7,398 条 CSV 原始记录逐字节保留；所有记录的原始换行及 CSV 表头、BOM 保留，记录顺序一致。
- 前三批各 1,000 张双项审核完成状态保留；状态分别为 707/272/21、847/142/11、354/530/116（顺序为 reviewed_annotation / negative_confirmed / reviewed_excluded）。
- 全库 8,398 张，双项完成 4,000 张，双项待审 4,398 张，无混合审核标志。
- 41 张排除原因：{'No Ball=0但空label': 13, '原不确定处置保留': 27, 'label格式或几何问题': 1}。保留用户框、分类和原处置，不将空框推断为无球。

批准前 metadata SHA256：`d9ad0e6f4184d75f11069e4de884988e60a76e3b5cd1640baeee1066e3412317`。批准后 SHA256：`6ecc9d6eee9b3c17a36873b2b395f9b10868d8012480afd2d7fd8b4d1985d5aa`。

依据：原始 `../batch-004-user-reviewed-snapshot.json`、`before/metadata.csv`、`before/inventory.json`、`approved-records.json`、`result.json`；机器核验结果：`verification.json`。本次核验只写本目录的 verification.json 和 REPORT.md。
