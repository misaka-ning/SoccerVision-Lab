# 数据版本导航

两个版本均完整保留；此索引不替代版本内的manifest、名单、统计或封存记录，不修改数据入口。

| 版本 | 角色 | 正式划分 | 其他材料 |
| --- | --- | --- | --- |
| [v0](v0/) | 原始审核数据及按来源划分、历史来源基准 | Train6925 / Val1223 / Test0 | 根metadata共8398记录；250项excluded单独隔离；人工label恢复点保留 |
| [v1](v1/README.md) | 冻结正式实验版本 | Train4346 / Val1223 / Test464 | buffer755、heldout_unused1360；五类去向共8148，另250排除仍在v0 |

v1 Test是同场次片段留出，与Train共享采集场次。buffer与heldout_unused是科研保留样本，不是垃圾。每版的images/labels/metadata、manifest、分集依据、统计、人工证据、轮次和初始化定义保持独立；不做合并、硬链去重或重新划分。

- v0依据：[划分说明](v0/SPLIT_POLICY.md)、[隔离manifest](v0/excluded/manifest.json)。
- v1依据：[分集报告](v1/REPORT.md)、[分配manifest](v1/manifest.json)、[统计](v1/statistics.json)、[验证](v1/verification.json)。
- 上游来源与审核链：[处理阶段导航](../dataset_processing/STAGE_INDEX.md)。

每次实验引用版本ID、实际冻结manifest/metadata/名单与内容哈希，不复制整份数据到实验目录。共享数据选择、路径适配和接口由另一个工作负责，本次不改YAML、名单或配置。新增数据/标签修订在将来建立新版本后重新封存，不覆盖v1事实。
