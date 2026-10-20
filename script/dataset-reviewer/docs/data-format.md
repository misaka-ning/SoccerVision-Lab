# 数据约定

## 数据集目录

```text
数据集根目录/
├── metadata.csv
├── dataset.yaml                  # YOLO 训练配置；审核程序不解析该文件
├── images/{train,val,test}/
├── labels/{train,val,test}/
├── .metadata-review-backups/      # 保存 CSV 时生成
└── .label-review-backups/          # 覆盖已有 label 时生成
```

审核程序读取 `metadata.csv`、图片和 label。训练配置建议随数据集维护，但不是界面加载的必需输入。同一图片与 label 使用同一 split 和同一文件名主干，例如 `images/train/example.png` 对应 `labels/train/example.txt`。

## metadata.csv

使用 UTF-8，可带 BOM。CSV 支持引号、逗号及字段内换行；每行列数必须与表头一致，列名不能为空或重复。

| 字段 | 要求与用途 |
| --- | --- |
| `图片` | 必需；单一文件名，不含目录或绝对路径；全表不能重复 |
| `split` | 必需；`train` / `val` / `test` |
| `Small`、`Occluded`、`Blurred`、`No Ball` | 必需；各自为 `0` 或 `1`，可同时命中多项 |
| `annotation_status` | 必需；标注来源、审核状态或不确定原因 |
| `scene_review_required` | 必需；`0` 或 `1`，1 表示场景需复核 |
| `label_review_required` | 推荐；`0` 或 `1`，1 表示 label 需复核；缺失时 label 审核与图形编辑禁用 |
| `preserved_box_count`、`auto_box_count` | 可选来源计数；前者控制保留框 / 候选框显示，人工改框不重算 |
| `label_review_note` | 可选；标注依据、不确定性、冲突说明 |
| `source_video`、`source_frame_idx`、`eye` 等 | 可选来源信息；工具保留未知附加列 |

场景标记分别表示小目标、遮挡、运动模糊和经人工确认无球；具体分类口径由数据集维护者确定。模型未检出不能直接推出无球。

## YOLO label

每行一个框：

```text
class_id x_center y_center width height
0 0.5 0.5 0.1 0.2
```

类别为非负整数，坐标为有限数，中心和宽高归一化到整张图片，宽高大于 0；框需位于图像范围内（解析器容许浮点边界误差）。当前足球数据约定为 `0 = football`，编辑器允许输入其他非负类别，不自动从 `dataset.yaml` 校验类别表。

空 label 是零框样本，缺失 label 是尚未标注或需补充的样本。格式错误不会因浏览或保存分类而被自动修复；在图形编辑器保存会用当前有效框重写整个 label，需人工补齐遗漏框。

## 审核状态

- `label_review_required=1` 或状态为 `auto_label_needs_review` / `needs_manual_bbox_annotation` 的样本进入待 label 审核筛选。
- 手工保存框：设置 `label_review_required=1` 和 `annotation_status=needs_manual_bbox_annotation`。
- 有效非空 label，且 `No Ball=0`：人工通过后设置 `label_review_required=0` 和 `annotation_status=reviewed_annotation`。
- 有效空 label，且 `No Ball=1`：人工通过后设置 `label_review_required=0` 和 `annotation_status=negative_confirmed`。
- 缺失、格式错误、框与 `No Ball` 冲突的 label 不能通过。通过时及保存前检查显示文件的 SHA256，变化后必须重新核对。

- 不确定状态：`uncertain` / `severe_blur` / `severe_occlusion` / `uncertain_bbox` / `temporal_only` / `fully_occluded`。通过受控操作设置，清除 `No Ball`，设置两项复核标记为1，保留现有 label。
- `reviewed_excluded`：用户明确完成复核后仍需保留的模糊、遮挡、不确定或技术无效样本；两项复核标记为0，原类别、label 与原处置原因保留。它表示审核已结束，暂不进入普通训练。导出至 `excluded/reviewed/{split}/images/` 与 `reference_labels/`，独立元数据包含原因，不计入 pending。
- 不确定状态不能直接通过 label 审核或改框，须「重新复核」进入待修正状态。重新复核后仍要完成两项审核。

`scene_review_required` 单独管理场景复核。普通 YOLO 不读取这些审核字段；必须使用工具导出的数据集，原目录不会自动过滤。

## 导出快照

仅 `reviewed_annotation` 或 `negative_confirmed`，且两项复核标记均为0的样本进入导出 `images/{train,val,test}` 和 `labels/{train,val,test}`。还需 label 存在、格式有效、类别为0、框不越界、正负状态与 No Ball 一致。已通过却不满足校验的记录会阻止整个导出；未审核样本不收录。

```text
新导出目录/
├── dataset.yaml                   # 仅指向下方 images/；包含导出目录绝对路径
├── metadata.csv                   # 仅正式检测样本，保留原字段
├── images/{train,val,test}/
├── labels/{train,val,test}/
├── uncertain/
│   ├── metadata.csv               # 不确定样本，保留来源、原 split、原因
│   └── <原因>/<原split>/
│       ├── images/
│       └── reference_labels/      # 可选；原图全名.txt，不生成缺失的 label
├── excluded.csv                   # 不确定样本和其余待审核样本的完整记录
└── export-summary.txt             # 规范版本、UTC 时间、源 CSV SHA256、集合数量
```

导出复制资料，源目录不移动文件。每次使用新目录；移动导出目录后应同步修改 YAML 中的 path。不确定样本通过 annotation_status 分组，无需把原始 split 改为 uncertain。旧 CSV 的未知来源字段全部保留，工具不会猜测缺失信息。

## 输出与恢复

分类保存更新 `metadata.csv`，手工画框保存更新对应 `.txt`；图片、split、来源信息与其他只读字段保留。CSV 备份存于 `.metadata-review-backups/`，已有 label 的原始字节存于 `.label-review-backups/<split>/`。新建 label 没有旧文件备份。

恢复前关闭编辑窗口并保留当前文件，再由维护者选取对应备份恢复；恢复 label 时同时核对 metadata 审核状态。产品没有自动撤销已落盘修改的恢复命令。
