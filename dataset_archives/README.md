# 冷归档与恢复规范

现有有效归档原位保留，不改名、不重压。权威登记为[CATALOG.csv](CATALOG.csv)；本轮只登记已有2918份CSV恢复包，不声称已经执行新的阶段归档。旧包及外置manifest均已核验，详见[核验报告](../reports/workspace-organization/EXISTING_ARCHIVE_CHECK.md)。

## 唯一归档单元

未来新包采用 `dataset_archives/<YYYY>/<stage>/<archive_id>/`。archive_id包含原阶段、封存UTC时间与版本；一ID一份不可变内容，不复用ID覆盖。以完整审核阶段或完整事务封存，before/proposed/applied/approved和原始label/metadata身份不被SHA去重或扁平合并。

每单元只保留一份payload、manifest.json、files.csv、VERIFY.json和RESTORE.md。manifest结构见[ARCHIVE_MANIFEST.schema.json](ARCHIVE_MANIFEST.schema.json)。

- manifest必须记录archive_id、source_paths、creation_time（含时区）、file_count、total_bytes、包sha256、原因、研究角色、依赖、成员映射、索引SHA和恢复规则。
- files.csv逐项记录source_path、member_path、entry_type、bytes、sha256、mode、mtime_ns、stage_id、operation_id和角色。每个完整workspace相对路径原样成为成员路径，不只存basename，不丢空label或空目录身份。
- payload SHA在包完成后写入外置manifest，避免把包含自身校验值的manifest再塞回包产生循环。旧包已有内置manifest的方式保持，不强行套新格式。
- VERIFY记录包SHA、精确成员数、逐项内容/路径/大小校验、异常成员检查、独立恢复位置与验证范围。RESTORE列出独立临时根、映射、依赖和冲突处理。

## 建立与恢复顺序

1. 获得具体操作授权；冻结精确来源清单、SHA、权限及前后路径，确认无并发写入。遇已有同名archive_id停止，不覆盖。
2. 新包与索引先写入独立新位置。创建归档与清退原件是两个动作；建包时保留所有源。
3. 检查包SHA、成员集合和计数、逐文件size/SHA、路径映射；拒绝越界路径及未审查的链接/特殊成员。原资料若有链接，先保守登记，不能悄悄改为内容副本。
4. 恢复到独立空临时目录，按files.csv全量核对（已存在旧包可明确记录全量流式+抽样落盘的核验程度），失败保留源且不宣称可回收。
5. 重要阶段若要清退原树，先完成全量独立落盘恢复核验、依赖确认、保存权限与原路径映射，再另行审批精确清退清单。压缩包存在或校验通过本身不授权删除。
6. 真正回填原位置前再次授权；目标存在/哈希不符即停止，不覆盖后来人工修改。恢复历史证据不代表允许执行历史写入脚本或回退现数据。

## 旧归档的适配

`review-metadata-backups-20261019-cleanup/` 使用旧式basename清单，保留原字节。登记明确 `metadata-backups/{name}` 成员对应创建时 `datasets/.metadata-review-backups/{name}`，现在逻辑来源为 `datasets/v0/.metadata-review-backups/{name}`。恢复先去独立目录，不自动写回live metadata。

现存10份散CSV与此旧包无名称/内容重合，316份人工label恢复点也不在旧CSV包覆盖范围。不要把既有13.66GB解压内容再次算作当前可回收空间。

归档默认本地/私有，不能因有索引就上传许可未确认的数据、图片、权重或含图证据。目录导航只链接权威材料，不生成第二套完整“最新备份”。
