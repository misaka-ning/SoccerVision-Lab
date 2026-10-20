# 第 7 批批准后独立核验

结果：PASS。独立读取当前数据集、批准前 metadata、inventory、用户复查快照及批准记录。

- 1000 张图片及 label SHA256 均与批准前一致；仅审核状态、双审核标记和 note 追加发生变化，原 note 前缀与其他全部字段保持。
- 本批 675 reviewed_annotation、325 negative_confirmed、0 excluded，1000 张双审核标记均为 0。
- 批外 7398 条原始 CSV 记录字节不变；BOM、表头、行序与所有换行保持。
- 前 6 批共 6000 张记录、媒体哈希与各批状态计数保持。
- 全库 8398 张，done 7000、pending 1398、mixed 0。
- 核验未写入 canonical 数据集。

完整检查与哈希见 verification.json。
