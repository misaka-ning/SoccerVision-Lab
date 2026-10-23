# 原始参考模型资产

此目录保存原始YOLO26s权重、从checkpoint提取的架构和历史身份清单。原权重已由 `original_best.pt` 更名为 `E0_original_best.pt`，字节及SHA256保持，不作为缓存清理或为每个实验重复复制。

| 文件 | 角色 |
| --- | --- |
| E0_original_best.pt | 原始参考权重；20,422,725字节，SHA256见下文 |
| original_model.yaml | 保存的原始架构定义；原结构已经包含C3k2 |
| baseline_manifest.json | 历史类别、模型元数据及身份记录；保持原字节 |
| the model is yolo26s | 0字节历史占位；删除仍待批准 |

原权重SHA256：`646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b`。

维护者于2026-10-19确认：该权重未见过当前Test，曾见过部分Train。此事实适用于以上哈希身份，具体成员/Val曝光不作额外推断。新事实记录在[本轮确认](../reports/workspace-organization/OWNER_ASSERTIONS.md)，旧材料中的unknown保留其历史含义。

参考权重含80类：0=person、32=sports ball；项目单类足球数据为0=football。E00须明确类别映射，E01记录兼容权重迁移；这里仅说明资产身份，不改变训练或推理接口。

来源授权与再分发范围未确认前只本地保留，不上传公开仓库。新实验引用原权重SHA；新权重另建唯一run和工件索引，不能覆盖此文件。
