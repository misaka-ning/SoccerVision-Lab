# 当前数据集划分（2026-10-19）

按用户指定来源划分，适用于images/labels中的8148张可用图片。左右目各计1张，球框、四类场景和人工审核结果保持。

| 来源 | 当前集合 | 可用图片 | 隔离图片（不参与划分） |
| --- | --- | ---: | ---: |
| 2026-10-13 18:15:31（前27分钟） | Train | 6212 | 226 |
| legacy | Train | 713 | 1 |
| 2026-10-13 10:47:48 | Val | 1154 | 22 |
| 2026-10-13 18:13:26 | Val | 69 | 1 |
| 合计 | Train6925 / Val1223 / Test0 | 8148 | 250 |

`images/test/`和`labels/test/`保留为空目录，待后续独立采集。dataset.yaml的test路径仍明确指向这个空目录；当前没有Test指标，不能把Val结果记成Test结果。Train/Val仍由同一个dataset.yaml读取。

根metadata.csv保留完整8398条审核历史。只修改1185条可用样本的split，保持行顺序、来源字段、四类场景、审核状态和备注。统计当前训练/验证数据必须过滤annotation_status=reviewed_excluded；250条排除记录及excluded下的文件、metadata和隔离manifest保持原样，其中原split仅表示隔离时的历史位置，并不构成当前Test数据。

legacy_train/val/test文件名前缀是旧导入命名，当前集合以目录和metadata.split为准；本次没有重命名图片，也没有修改任何label内容。

此前科研审计是重分前冻结快照，包含旧split和旧绝对路径，不应当作当前划分报告。其已打包缩略图和证据页仍是历史证据。本次来源归组使用该审计中经图SHA验证的provenance，不改写旧审计。按视频分组解决已知录像被拆到Train/Val的问题，但不代表重新获得科研审计PASS，也不补足尚未采集的独立Test。

执行清单、前后映射、备份、日志和独立验证见 ../dataset_processing/source-resplit-20261019/ 。不要直接重跑迁移脚本。回退前须核对当前文件SHA及目标冲突，保留任何后续人工修改。
