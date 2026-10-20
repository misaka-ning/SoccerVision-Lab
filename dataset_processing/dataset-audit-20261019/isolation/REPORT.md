# 250张已排除样本隔离独立核验

结论：**PASS**。核验时间：2026-10-19T03:48:15.296881+00:00。

本次核验针对用户在只读审计之后明确授权的窄范围文件移动：250张 `reviewed_excluded` 图片及其250份label移至 `datasets/excluded/`，备份保留在本审计的 `isolation/backup/`。原始审计baseline、metadata、YAML、split字段和8148张可用样本均按冻结基线核验。

| 检查 | 结果 |
| --- | --- |
| 8398张图片及8398份label与冻结基线逐SHA256一致 | 通过 |
| 500份隔离文件与500份备份逐字节一致 | 通过 |
| 250张原图片路径及250份原label路径全部不存在 | 通过 |
| active images / labels 精确各8148，无额外或缺失文件 | 通过 |
| excluded images / labels 精确各250，train243 / val6 / test1 | 通过 |
| canonical metadata完整保留8398原始记录，隔离metadata精确250原始记录 | 通过 |
| metadata及dataset.yaml字节SHA不变 | 通过 |

迁移前原始训练目录包含8398张，其中250张已排除；迁移后active目录仅8148张可用样本，另250张通过归档manifest解析。`datasets/metadata.csv`仍是8398条全量审核记录，不能把已归档记录计为丢失文件。归档样本仍是排除参考，空label不自动成为负样本。

- metadata SHA256：`cb2386ef97c2f864cad27adf8fc06dc6fc74cea2caf828f32a685abc05985ef9`。
- dataset.yaml SHA256：`7781d543cc43364f2a2598ff596adb05a8e80b4547af40195665565a8eef05b6`。
- 全部逐文件哈希、路径、分集与备份证据见 [verification.json](./verification.json)。
- 本核验只读canonical数据；没有重写标注、场景、审核状态或分集，没有训练或模型推理。
