# 足球数据集分批重新审核（2026-10-15）

当前数据集 `/home/misaka/workspace/datasets` 共 **8,398 张图片**，全量重置时撤销了此前球框和场景分类的通过状态；之后用户已保存的复查结果继续保留。原始图片、数据划分、来源字段及原有备注保留；空 label 仍保留，不能只根据空文件判断无球。

## 审核流程

1. 助手逐图检查全景，核对现有框局部、漏球、误检、边界及四类场景；明确问题修为候选，不确定问题写明原因。
2. 用户在 Qt 审核工具中复查、调整球框和分类，最后手动通过。助手的“high”仅是预审把握较高，**不等于通过审核**。
3. 每批 1,000 张，最后一批 398 张；同帧左右目未跨批拆开。批次仅是浏览名单，保存直接回原始 `metadata.csv` 和 `labels/`，不创建另一份训练数据。

## 启动

```bash
/home/misaka/workspace/script/review_football_batch.sh 1
```

第一批优先看存在疑点的 **252 张**：

```bash
/home/misaka/workspace/script/review_football_batch.sh 1 --priority
```

按批次完整复查时使用第一条命令。批次号可改为 2–9；这些批次目前仅重置待审核，**尚未完成本轮助手预审**。

| 批次 | 张数 | 本轮助手预审 | 用户最终审核 |
| --- | ---: | --- | --- |
| 1 | 1,000 | 已完成 | 用户已复查疑点；其他图片按 50 张分组继续 |
| 2 | 1,000 | 待处理 | 全部待审核 |
| 3 | 1,000 | 待处理 | 全部待审核 |
| 4 | 1,000 | 待处理 | 全部待审核 |
| 5 | 1,000 | 待处理 | 全部待审核 |
| 6 | 1,000 | 待处理 | 全部待审核 |
| 7 | 1,000 | 待处理 | 全部待审核 |
| 8 | 1,000 | 待处理 | 全部待审核 |
| 9 | 398 | 待处理 | 全部待审核 |

## 其他图片按 50 张一组复查

用户复查疑点后，创建固定名单时从其余 748 张中再排除已双项通过的 3 张，剩余 **745 张，15 组：14 组各 50 张，末组 45 张**。左右目同帧不跨组，疑点里用户保留待定的图片不混入这些组。

```bash
/home/misaka/workspace/script/review_football_batch.sh 1 --group 1
# 组号可改为 2–15；查看实时进度：
/home/misaka/workspace/script/review_football_batch.sh 1 --groups
# 打开首个仍有待处理项的固定组：
/home/misaka/workspace/script/review_football_batch.sh 1 --group next
```

启动后窗口加载全部 745 张，按每页 50 张平铺，使用“前50张 / 后50张”跨组翻页；`--group N` 仅指定起始页。分类仅显示值为 1 的中文名称，全为 0 时留空。

固定名单及创建记录位于 `batches/batch-001-remaining-50/`。名单不会随审核进度重新分配，保存直接回原数据集。球框及场景需分别确认；保留不确定样本时，该组仍显示待处理，可直接指定下一组继续。

## 文件

- `batches/batch-001.txt` 至 `batch-009.txt`：固定完整批次名单。
- `batches/manifest.csv`：每张图片的批次和顺序。
- `batch-001/REPORT.md`：第一批预审结果。
- `before/metadata.csv`：全量重置前备份；`before/inventory.json` 记录原始图片、label 的 SHA256、尺寸、坐标和 metadata。
- `applied/`：第一批写入前 metadata 和 1,000 个 label 的原样备份、建议、逐文件结果。
- `verification.json`：全库一致性核对结果；`validation.json`：结构校验明细。

**不要直接用旧备份覆盖现有 metadata.csv**：会丢失之后的人工复查。写回工具有全字段及文件哈希保护；本批次写入时没有冲突或失败。
