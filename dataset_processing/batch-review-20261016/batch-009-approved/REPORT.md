# 第9批用户确认批准独立核验

结论：PASS。独立脚本仅写本审核证据，未写 datasets。

- 本批398张：344张有球通过、54张无球通过、0张排除。
- 398张原图与 label 的 SHA-256 均与用户审核后的 fresh snapshot 一致。
- 仅 annotation_status、两项 review flag、label_review_note 改变；四类分类、split、框数元数据、来源字段及其余字段保持。
- 原备注完整保留，并追加2026-10-19用户明确完成审核的确认。
- 批外8000条 CSV 原始记录逐字节保持；8398条顺序、表头、UTF-8 BOM 与每条记录换行保持。
- 全数据8398张两项审核标记均为0；无待审核记录。
- reviewed_excluded 继续作为已审核保留样本，不能当作无球负例。

详情见 verification.json。
