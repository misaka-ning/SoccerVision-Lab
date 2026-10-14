# 分类、标注及人工审核接口

## 数据结构

```text
football_dataset/
├── images/{train,val,test}/
├── labels/{train,val,test}/
├── metadata.csv
└── dataset.yaml
```

整理后自动识别每张新保留图片中的足球并写入 label；有球写 YOLO 框，视觉确认无球也创建零字节 `.txt` 文件，不依赖推理工具是否输出空文件。原有用户 label 保持不变。同一图片与 label 使用相同 split 和 stem，例如 `images/train/<id>_left.png` 对应 `labels/train/<id>_left.txt`。本机 CSV 使用 `utf-8-sig`（BOM），读写保留字段次序及未知列。一张图一行，不把多标签分类拆成多份图片目录。

新建数据集的 YAML：

```yaml
path: /绝对路径/football_dataset
train: images/train
val: images/val
test: images/test
names:
  0: football
```

已有 YAML 应先读取，保留合理的配置及实际类别映射；本机足球数据集只有 `0 football`。

## metadata.csv

本机字段如下，新数据按这个接口追加；已有更多列要保留：

| 字段 | 含义 |
|---|---|
| 图片 | 文件名，全数据集唯一，禁止不同来源同名覆盖 |
| Small, Occluded, Blurred, No Ball | 每项整数 0/1，独立多标签；确认普通球样本全部为 0 |
| split | train / val / test，保留已有划分 |
| annotation_status | 下表中的标注状态 |
| scene_review_required | 场景分类存在不确定性时为 1，否则 0 |
| label_review_required | 自动框、待画框或冲突为 1；明确人工确认/原有 GT 为 0 |
| auto_box_count | 本次由模型、录像候选或助手视觉补画、尚未被用户确认的框的来源计数 |
| preserved_box_count | 原有框的来源计数 |
| label_review_note | 不确定点、疑似漏球、冲突、候选来源等说明 |
| source_video | 视频绝对路径，区分物理剪辑和原来源 |
| source_frame_idx | 相对于 source_video 的零起始帧索引；剪辑时另记原视频与原索引映射 |
| eye | left / right / mono |

`auto_box_count` / `preserved_box_count` 是来源记录，人工调整框后不要求和当前框数相等。不要在 CSV 中存储密码。

## 四类判定

- **Small：** 远距离小目标。当前约定以单目图长边归一到 672 为标尺，球的完整最长边约 ≤40 px 可作初始阈值；阈值要记入本次报告并允许覆盖。裁边/遮挡时参考相邻清晰帧的完整尺寸，不能只量残留部分；模糊边界或约 40 px 的临界尺寸无法可靠判断时置 `scene_review_required=1` 并注明依据。大球仅露出小角不直接算远距离小球。多球图只要一个可见球符合即可。
- **Occluded：** 任何明确前景遮挡，包括脚、腿、手、箱体、器械等。仅触碰球、正常背面不可见、图像边缘裁切不算遮挡。完全隐藏且无法定位的球不生成想象中的框。
- **Blurred：** 球本身或整体图像存在可见拖影/运动模糊。只有手脚模糊、分辨率低或 JPEG 轻微软化，不直接标记球运动模糊。
- **No Ball：** 视觉确认画面没有可见足球时为 1，并实际创建同 split、同 stem 的零字节 `.txt` label 文件；即使推理工具对无检测图片不输出文件，也要补建。无球时 Small/Occluded 通常为 0；整体模糊的无球图可以同时 `Blurred=1, No Ball=1`，不要将四项误做互斥类别。检测结果为空或低置信度不足以确认无球。灰球、黑白球及背景球都须检查，不能因颜色或器械附近的位置忽略。真实鞋、脚轮等可以成为困难负样本。

不确定是否有球：`No Ball=0`，`scene_review_required=1`，在 note 中说明；没有可靠框则 label 缺失并待补。已有人工 `No Ball=1` 与新候选矛盾时保留人工值，记录冲突并设置审核，不能静默更改。首次自动分类的其余不确定项按当前最合理观察给 0/1 并置场景审核，不用空值表示“不知道”。普通确定样本无需强行归入某个困难类别。

## YOLO 框与状态

提帧、去重和分类完成后自动执行本节标注，无需用户另行要求。优先使用用户指定或本地可用的 YOLO 模型，结合逐图视觉复核；没有可用模型时由助手视觉识别并写框。不能因没有模型只交付图片。

每个目标一行：`0 x_center y_center width height`，后四项相对于原生单目图宽高归一化，正宽高、合法边界。待审核标记只写 CSV，label 中不加第六列、注释或置信度。框覆盖可见足球的完整物体范围，避免把同一球的花纹拆成多个框；严重遮挡边界不确定时注明。多个真实可见球分别标。

若模型是 COCO，football/sports ball 通常是其自身类别编号（例如 32）；读取实际 `model.names` 后映射为数据集 0，不能因为权重叫 best.pt 就将模型类别 0 当足球。日志的最终有效检测与候选分开使用，低分候选仅辅助查漏。记录模型、阈值和候选来源，不把候选分数当分类真值。助手看图补画的框也属自动预标注，不能因此写成 `reviewed_annotation`。

| annotation_status | label 文件 | label_review_required |
|---|---|---|
| auto_label_needs_review | 一个或多个候选足球框 | 1 |
| needs_visibility_review | 未能确认球/框，通常缺失 | 1 |
| needs_manual_bbox_annotation | 已知有球但不能可靠画框，缺失 | 1 |
| negative_confirmed | 视觉确认无球，必须存在的零字节 `.txt` 文件 | 0 |
| provided_annotation | 原有用户标注，按已有内容保留 | 保留原值，通常 0 |
| reviewed_annotation | 用户明确确认后的标注 | 0 |

交付前核对本次确认无球的每张图片都有对应零字节 label；没有文件属于标注流程遗漏，应补建后再校验。未能确认是否有球或无法可靠画框的缺失 label 则保留明确待审核状态和原因。缺失 label 与已确认的空 label 必须区分。YOLO 训练可能把缺失 label 当背景，而且不会读取 CSV 自动排除待审核行；训练前必须完成审核或另建只含确认样本的训练子集。

## 现有数据保护与审核

追加视频时不重新计算现有分类、不改原有 label。用户另行要求重新分类时按字段识别人工修改：有基线则逐字段保护；无基线则保留现值并提交分类建议供审核，不猜哪些是自动值。用户明确要求重写某个范围/字段时才按该范围更新。不要用旧说明中的数量或旧 pending 清单覆盖实时 CSV。

审核工具存在时：

```bash
/home/misaka/workspace/script/dataset-reviewer/review_dataset.sh --dataset /绝对路径/football_dataset
```

本机工具显示 label 和分类，可改分类；Enter/保存分类不代表通过球框。label 需显式点击审核通过，待补框用外部标注工具编辑后重载。Qt 默认 `~/Qt/6.8.3/gcc_64`，可用 `QT_PREFIX` 覆盖，`--build-only` 必须独占，不与 dataset 参数混用。未有该工具时仍交付标准数据和清单，不把它作为硬依赖。
