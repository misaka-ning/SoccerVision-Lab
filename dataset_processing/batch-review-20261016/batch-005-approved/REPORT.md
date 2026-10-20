# 第 5 批人工完成审核独立核验

用户已明确确认本批 label 和场景审核完成。本次从原始用户审核快照、批准前 CSV、批准记录与正式 datasets 独立核验。

- 第 5 批共 1,000 张：498 张 reviewed_annotation、488 张 negative_confirmed、14 张 reviewed_excluded；各图状态由现有 label 与快照处置独立复算一致。
- 批内仅 annotation_status、label_review_required、scene_review_required 与追加 label_review_note 可变化；两项审核标志全部为 0，原注记前缀、四项分类、split、来源字段、计数及所有未知列全部保留。
- 1,000 张图片及 label 的 SHA256 与原始用户审核快照、批准记录全部一致，图片和 label 未写入。
- 批外 7,398 条 CSV 原始记录逐字节保留；所有记录的原始换行及 CSV 表头、BOM 保留，记录顺序一致。
- 前四批各 1,000 张双项审核完成状态保留；状态分别为 707/272/21、847/142/11、354/530/116、725/234/41（顺序为 reviewed_annotation / negative_confirmed / reviewed_excluded）。
- 全库 8,398 张，双项完成 5,000 张，双项待审 3,398 张，无混合审核标志。
- 14 张排除原因：{'原不确定处置保留': 14}。保留用户框、分类和原处置。

批准前 metadata SHA256：`1da9d2c60f6fa4ddd210c5beb9dbcf927c0343093859f526cbffca94b15b35aa`。批准后 SHA256：`4bac2d79cff7949dd19d9cebb5913a5ca9a3c7db91ce9a9f0d0602bf4132aab9`。

依据：原始 `../batch-005-user-reviewed-snapshot.json`、`before/metadata.csv`、`before/inventory.json`、`approved-records.json`、`result.json`；机器核验结果：`verification.json`。本次核验只写本目录的 verification.json 和 REPORT.md。
