# 本轮维护者确认的模型事实

确认日期：2026-10-19（Asia/Hong_Kong）。依据为维护者在本次任务中的直接说明，不来自checkpoint时间推断。

- 原始YOLO26s权重 `baseline/original_best.pt` **未见过当前Test，但曾见过部分Train**。
- 文件大小20,422,725字节，SHA256：`646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b`。本轮实际内容清单与原manifest一致。
- 这一确认适用于该具体文件身份及当前Test；不推断它见过全部Train，也不补造Val曝光、具体训练成员、旧超参数或来源授权。
- `datasets/v1/weight_exposure.json` 等旧材料中的unknown记录当时的信息状态，原字节保持。新实验索引引用本文件说明更新后的事实，不回写旧证据。
- v1仍是同场次片段留出；权重未见Test与采集场次独立性是不同问题。来源和再分发许可仍需独立确认，本轮不上传。

原权重、架构与历史manifest完整保留；本轮不加载或重写checkpoint，不启动评估或训练。
