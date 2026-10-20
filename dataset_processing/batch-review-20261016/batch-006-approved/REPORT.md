# 第 6 批人工完成审核独立核验

用户于 2026-10-19 明确确认本批 label 和场景审核完成。独立核对原始用户审核快照、批准前 CSV、批准记录与正式 datasets，结果 PASS。

- 1,000 张均双项审核完成：446 张 reviewed_annotation、507 张 negative_confirmed、47 张 reviewed_excluded；状态由现有 label 与原处置独立复算一致。
- 批内仅 annotation_status、两项审核标志及追加 label_review_note 变化；原注记前缀、四类分类、split、来源、计数及未知列全部保留。追加确认日期准确为 2026-10-19。
- 1,000 张图片与 label SHA256 与用户审核快照及批准记录完全一致。
- 批外 7,398 条 CSV 原始记录逐字节保留，全部记录换行、表头、BOM 和顺序保留。
- 前五批各 1,000 张双项完成状态与原计数不变；全库 8,398 张，完成 6,000、待审 2,398、混合标志 0。
- 47 张排除原因：{'原不确定处置保留': 44, 'No Ball=1但非空label': 3}；保留原框及场景值。

批准前 metadata SHA256：`c4c909904a3c397c22c11cfc41fcf1cd3c01c1d5f27f5b889938870bce2e197d`；批准后：`9cf8f0cb61a87f52da7ea44ee4aa4a087b89003e3eaeaea494e510ab2307889c`。

本次核验只写 verification.json 与本报告，未改正式数据。
