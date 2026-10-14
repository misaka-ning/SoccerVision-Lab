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
| `annotation_status` | 必需；标注来源或审核状态 |
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

`scene_review_required` 单独管理场景复核。`label_review_required=0` 不会让训练程序自动排除其他未确认状态；正式训练子集由维护者根据文件和审核结果确定。

## 输出与恢复

分类保存更新 `metadata.csv`，手工画框保存更新对应 `.txt`；图片、split、来源信息与其他只读字段保留。CSV 备份存于 `.metadata-review-backups/`，已有 label 的原始字节存于 `.label-review-backups/<split>/`。新建 label 没有旧文件备份。

恢复前关闭编辑窗口并保留当前文件，再由维护者选取对应备份恢复；恢复 label 时同时核对 metadata 审核状态。产品没有自动撤销已落盘修改的恢复命令。
