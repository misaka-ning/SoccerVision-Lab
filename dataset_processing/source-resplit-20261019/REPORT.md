# 按录像来源重分Train/Val（2026-10-19）

已按用户明确要求完成：18:15:31视频及legacy用于Train，10:47:48和18:13:26视频用于Val。Test暂空，等待后续独立补采。该操作只针对8148张可用图片；250张排除样本保持在excluded中。

| 来源（均为2026-10-13录像） | 当前集合 | 可用图片 | 排除图片（继续隔离） |
| --- | --- | ---: | ---: |
| 18:15:31，前27分钟 | Train | 6212 | 226 |
| legacy旧图片 | Train | 713 | 1 |
| 10:47:48 | Val | 1154 | 22 |
| 18:13:26 | Val | 69 | 1 |
| 合计 | Train6925 / Val1223 / Test0 | 8148 | 250 |

左右目单目图片各计1张。三段录像按来源整体分组，legacy整体进入Train，不再按旧legacy_train/val/test文件名前缀决定集合。文件名保持原样。

## 实际变更

- Train→Val：1006组图片及label。
- Test→Val：105组。
- Val→Train：52组。
- Test→Train：22组。
- 共移动1185组、2370份文件；其他6963张可用图片已在目标集合中。
- metadata只修改上述1185行的split。行顺序、字段值、四类场景、审核状态、备注和原来源字段均保持。未改任何图片或label内容。
- dataset.yaml保留train/val/test原路径，增加来源说明及Test暂空注释；目标类别仍为0=football。
- 更新工作空间README的当前统计，新增datasets/SPLIT_POLICY.md。未改训练脚本、参考模型或已冻结的旧审计。

## 校验结果

迁移事务及另一份独立实现的验证脚本均为PASS，详见[result.json](./result.json)及[verification.json](./verification.json)。

1. 全量8398张图片及8398份label的SHA256与迁移前逐一一致，包括250张隔离图片及label；文件权限保持。
2. 2370份已移动文件的备份与目标文件一致，原路径已不存在，无覆盖冲突。
3. active图片与label路径集合严格对应：6925/1223/0；没有孤立文件。原250项隔离记录、metadata和manifest未变。
4. 当前metadata逐字段比较：只有1185个split变化，其他字段不变；排除行完全不变。
5. 迁移按SHA恢复的来源provenance分组；独立验证另用文件名前缀归组交叉核对，每个来源只属于指定集合。
6. 实际安装的Ultralytics8.4.173文件发现：Train6925、Val1223，全部label存在，excluded读入0。Test空目录按预期报无图片，没有拿Val替代Test。
7. `script/model-training/train.py --dry-run`退出0，仅检查基本配置；未实例化模型、未训练、未计算任何评估指标。
8. 源数据没有遗留.cache或review.lock；Qt审核锁在事务结束后释放。验证的运行配置放在本次validation目录。初次验证因配置父目录未建立回退至/tmp/Ultralytics，修正为预建目录后重新全量验证通过，最终配置路径见verification.json。

| 当前可用集合 | 图片 | 有球图 | 无球图 | 足球框 | Small | Occluded | Blurred |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Train | 6925 | 4407 | 2518 | 4562 | 1185 | 1181 | 2013 |
| Val | 1223 | 813 | 410 | 855 | 442 | 235 | 265 |
| Test | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

困难场景允许重叠；Blurred可能与No Ball同为1。上表场景为图级数量，不等于专项Recall的实例分母。

## 排除历史与旧审计

根metadata仍有完整8398行。250条reviewed_excluded继续保留隔离时的历史split（243/6/1），其文件实际在datasets/excluded中；这不意味着当前Test还有1张可用图片。统计当前集合时先过滤排除行，并核对active目录。

dataset-audit-20261019是本次重分之前的冻结审计，包含旧分配和旧绝对路径，不应解释为当前划分。已打包的旧缩略图/证据页仍是历史证据；当前路径映射请查本目录split_changes.csv。旧审计未被覆盖，也没有据此次分组自动改成PASS。当前Test尚未采集，不能报告Test性能。

## 备份与复现边界

- [plan.json](./plan.json)：8398项前后路径、内容SHA、来源及明确授权。
- [split_changes.csv](./split_changes.csv)：按图片记录来源、旧/新split与路径，含隔离历史记录。
- [split_distribution.csv](./split_distribution.csv)：当前可用集合的数量及场景统计。
- before/metadata.csv、before/dataset.yaml、before/workspace-README.md保留迁移前原字节；before/files/保留2370份移动文件副本。
- journal.jsonl记录实际移动及配置写入。scripts/resplit_sources.py使用本机Qt审核锁，防止迁移期间审核工具同时保存；任何事务异常会尝试回滚并保留证据。
- 不要再次直接执行迁移脚本。回退必须在审核锁下核对当前SHA、原路径缺席及目标冲突，不覆盖后续人工编辑。核验脚本只读源文件，输出写入本次目录。

本次metadata SHA256：`fed79f82abfd40b21e01c77e22bdbb851edb53e80b541dc9bd9adf7ceb12181c`。

本次dataset.yaml SHA256：`b80d9d0d7e2468ab53b37ecc50cc16c2582137abbf38d89a87f8c55b45c88c91`。
