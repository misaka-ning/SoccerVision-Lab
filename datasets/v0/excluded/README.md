# 已审核但暂不训练的250张参考样本

用户于2026-10-19明确要求隔离。图片和label保持原始字节，内部按images/labels及原train/val/test保存，不自动作为无球负样本。

根目录metadata.csv仍是完整8398张审核历史，本目录metadata.csv为250条原始记录副本。根metadata的reviewed_excluded图片实际路径按本目录manifest.json解析；没有修改原split字段。当前根images/labels只留8148张可用样本。

manifest.json记录原路径、现路径、SHA256和回滚规则；审计目录isolation/backup保留移动前副本。恢复前必须核对哈希和目标冲突，不覆盖任何后续人工修改。
