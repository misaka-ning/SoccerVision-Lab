# 审计复算说明

本目录是2026-10-19科研审计的冻结证据包。**不要在本目录直接重跑脚本，也不要为了复跑再次执行 `scripts/isolate_excluded.py`。** 隔离是用户后来明确授权、已经完成的一次性文件移动，不是复算步骤。

`data/inventory.json`、`data/gray128x72.npz` 和 `annotation_issues_base.csv` 记录的是**隔离前**的8398张全量基线。当时250张 `reviewed_excluded` 仍在原始images/labels目录；这条历史发现不能解释为当前仍混入训练。

当前文件状态是active images/labels各8148份，另有250张图片及250份label位于 `datasets/excluded/{images,labels}/{train,val,test}/`。归档分集为train243、val6、test1。`datasets/metadata.csv`仍完整保留8398条审核记录，归档metadata仅250条原始记录。排除记录的当前路径应通过 `datasets/excluded/manifest.json` 或本目录 `isolation/plan.json` 解析，不能把冻结inventory中的250个原路径不存在误报成文件丢失。`isolation/verification.json`保存了全部8398图及8398份label的基线SHA核验与500份归档/备份逐字节比较结果。

## 先建立独立复算副本

1. 将本证据包复制到新的独立输出目录，保留原始输入另作只读副本；不要把新结果写回本目录。要验证原始数据，优先使用数据的独立副本；不需要把归档文件恢复到canonical原路径。
2. 在**新副本**中检查每个脚本的 `BASE`、`OUT`、`ROOT`、`DATA`、`D`、`SAFE`、`SOURCES`、`HISTORY` 和绝对路径。部分脚本用 `__file__` 推导输出目录，另一些仍硬编码本次审计位置；只复制脚本并不足以安全重定向。所有输出、配置、缓存、物理测试副本和图表路径都必须指向新目录。
3. 读取冻结的 `source-metadata.csv`、inventory、特征和来源证据。需要读取图片或label时，先尝试原active路径，再按隔离manifest映射到archive；核对基线SHA后读取。所有映射修改仅发生在复算副本的代码或派生数据中，不改原inventory、metadata、YAML或split字段。
4. 如需从图片重新提取inventory特征，须在副本扫描器中加入上述只读路径解析，或扫描独立的数据副本。当前 `inventory_audit.py` 默认直接查找隔离前路径；原位重跑会把已归档250项误当缺失，并覆盖冻结结果。`--enrich-excluded`也会重写审计CSV/summary，不能对本目录运行。
5. 保持单进程、CPU单线程和既有依赖；不自动安装依赖，不启动训练、验证评估或生产检测推理。缓存重定向与Ultralytics副本验证仍需保留。最终环境和脚本SHA以主manifest为准，本说明不另造一套版本清单。

## 输入与执行依赖

下表说明数据依赖，不是可在本目录逐条执行的命令列表。采用冻结中间结果时，可以跳过相应上游计算。

| 顺序/阶段 | 脚本 | 主要输入与条件 | 派生结果 |
| --- | --- | --- | --- |
| 基线扫描，可跳过 | `inventory_audit.py` | 冻结metadata、图片/label；在副本加入archive解析 | inventory、灰图NPZ、基线异常/分布CSV、哈希清单 |
| 来源与描述统计 | `provenance_stats.py` | 冻结inventory及8份历史文本证据；将副本的 `SOURCES` 改为下述缓存映射 | provenance、时间邻近对、来源/场景分布及统计精度资料 |
| 全局特征，可跳过 | `embeddings.py` | inventory中8148张usable图片、已保存官方MobileNetV3-small权重；原图只读 | 576维L2向量及模型/预处理说明 |
| 自动相似性检索 | `similarity_audit.py` | inventory、gray NPZ、embedding NPZ、provenance及temporal_pairs.csv | 自动候选、阈值分布、SSIM、跨集合CSV/JSON |
| 证据图渲染 | `render_pair_evidence.py` | 候选、inventory及解析后的当前图片路径 | 按pair编号的叠框对照页；不产生人工判断 |
| 训练入口与抽样验证 | `training_safety.py` | 当前数据状态、审核metadata、项目训练入口和既有依赖；所有测试/配置输出重定向 | 仅文件发现、隔离副本label检查、安全报告，以及固定种子64张分层抽检清单/页面；不训练模型 |
| 助手视觉观察，不能自动替代 | 无一键脚本 | 实际打开页面/原图；对照已有人工观察文件 | 成对及抽样观察，用户review字段仍留空 |
| 合并视觉优先级 | `apply_visual_triage.py` | 自动候选与三份冻结的成对观察JSON | 最终复核优先级、跨集合CSV及triage summary |
| 汇总与展示 | `finalize_outputs.py`、`build_review.py` | 基线CSV、最终候选、来源/精度统计、抽样观察及归档状态 | 当前路径的标注/排除清单、图表和离线复核HTML |
| 当前隔离状态的独立检查，可单独执行 | `verify_isolation.py` | 冻结inventory/summary、plan/result、archive manifest、当前文件及备份；在副本重定向验证输出 | 新的verification与报告；不移动文件 |

`scripts/isolate_excluded.py`仅保留为本次已执行操作的审计凭据，**不在上述依赖链中，不应复跑**。原始隔离journal、备份、plan/result和当前archive manifest共同解释迁移，不需要通过重演移动来验证。

`training_safety.py`的 `--phase safety` 与 `--phase sample` 可分开；若重算某一阶段，只写新输出目录。隔离前后扫描口径不同，复算当前入口应得到8148张active，不能要求它再次得到隔离前8398张。既有 `.cache` 仅按安全读取规则检查，不反序列化历史pickle，不创建或重写canonical缓存。

## 可直接重用的冻结输入

- `data/inventory.json`按metadata原顺序排列，`index`从0开始。图片/label SHA、归一化框、标签状态和哈希方法定义见 `data/inventory-summary.json`。重新生成后的记录顺序必须先核对，再与任何NPZ连接。
- `data/gray128x72.npz`包含 `gray:uint8[N,72,128]` 与 `indices`；可直接重算候选SSIM，不必再次解码所有图片。它是整幅缩放灰图，没有裁切或几何对齐。高风险对的256x144精化SSIM与可选平移诊断仍需读取对应源图，不能把128x72数值冒充成较高分辨率结果。
- `data/embeddings.npz`包含8148张usable图片的576维L2特征与原inventory索引；可直接做归一化内积检索。模型不是DINOv2，整图224x224缩放也不是官方分类中心裁剪，限制见 `data/embedding-model.json`。
- `data/provenance.json`、`data/temporal_pairs.csv`及既有来源统计可直接作为冻结检索输入；如要重建来源判定，使用下面的8份缓存文本并逐项核对图SHA，而不是仅相信数字文件名或相似背景。
- `data/legacy-pair-visual-review.json`、`data/medium-pair-visual-review.json`、`data/root-temporal-visual-review.json`和 `data/visual-findings.json`保留了实际查看图像后的助手观察，可用于重建最终展示和风险优先级。它们不是由图像分数自动推出的真值，也不是用户已经通过审核的结果。

自动检索重跑可能改变排序与 `pair_id`。复用人工观察前，必须核对pair对应的两张文件、顺序、源SHA和证据页，不可只按相同编号机械关联。已记录的页面SHA只能证明观察所对应的证据版本，不能把人工判断变成可由脚本保证复现的结论。重新审阅应产生新观察记录，保留原观察；所有用户 `review_status` / `review_result` 初始仍为空。

## 历史文本证据缓存

`data/provenance-evidence/sources.json`列出10份文本的原路径、缓存路径、SHA256及字节数：8份历史来源证据，另2份本次实际读取的规范/基线参考文本（`review-policy.json`和既有最终统计 `REPORT.md`）。缓存按原字节复制；8份来源证据逐项匹配 `data/provenance.json` 中historical_evidence的SHA与大小，另2份逐项匹配 `data/inventory-summary.json` 中 `source_hashes_before`。未复制任何历史视频或媒体。

这些缓存足以重建本次历史清单映射，无需依赖临时目录继续存在。在新副本的 `provenance_stats.py` 中，将每个 `SOURCES[evidence_id]` 映射到对应 `cache_relative_path`。原 `data/provenance.json`仍保留当时的原始证据路径，便于追溯，不为便携性改写已冻结来源记录。

若在副本重新运行inventory扫描，把其 `POLICY` 和 `REPORT` 引用分别改为上述两份缓存规范文本，以保持当时使用的口径与基线；这些参考文本的缓存不授权修改当前标注，也不要求追溯重写旧审核批次。

文本清单和当前图SHA相符，可支持特定图与历史来源的关联；它们不自动补齐未知的真实采集session。尤其714张legacy图，不能从共用桌面背景创造session或帧号。视觉近重复、同录像时间相邻、同采集事件和科研泄漏须继续保持证据层次区别。

主要报告、划分建议及本说明还包含人工分析文字，不是完整的自动生成流水线。复算应核对可计算统计与证据关系，并明确记录新运行与冻结版本的差异，不以覆盖旧报告来消除差异。
