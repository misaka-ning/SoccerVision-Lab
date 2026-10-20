# 第6批足球数据集预审记录

日期：2026-10-16。正式数据集：`/home/misaka/workspace/datasets`。

固定名单`../batches/batch-006.txt`共1000张，`video_4bec9c343db72928_frame_00012688_left.png`至`video_4bec9c343db72928_frame_00016535_right.png`。原图、来源与train/val/test划分保持。

## 本批审核口径

延续用户第5批开始的[审核说明](/home/misaka/workspace/dataset_processing/batch-review-20261016/REVIEW_POLICY.md)：足球被画面边缘截断（包括半球）也标遮挡；真实前景覆盖标遮挡。No Ball按最终label判定：零框为1，非空为0。本批546张空label全部标1、454张有框全部标0；待补框或身份待确认的空label也按该口径标1，具体疑点保留在理由及审核状态中。

Small以完整球尺度折算到图像长边672后约40像素判断，大球露出的小残片不自动算Small。Blurred要求可辨方向性球/相机拖影，低像素软化和单独脚移动不自动算。四类可重叠，均不属于时全0。已人工审核的前5批不追溯改写。

## 预审结果

- 逐幅实际查看1000张原生全景、447个原有框；证据为500页原生全景与58页旧框局部对照，另有疑点原生网格、放大及前后对照。
- **20份label变更**：11张原空label补足球候选；5份非空label修正，其中2份把机器人脚误框移至同图真正足球，其他修正偏位或收紧包含机器人腿/背景的范围；4份人物鞋面或机器人白足误框清空。框数447→454。
- 全部20项改框经第二遍原生对照，坐标与最终提案逐一吻合，见[二审记录](./replacement-second-review.json)。新框只取当前可见范围，保留真实运动软边，不补遮挡轮廓。
- 3张只有底边数行亮点或强白片的补框候选撤回，保留空label与可见性疑点，见[撤回记录](./withdrawn-candidates.json)。不以另一目或相邻帧替代当前图证据。
- 2张完整足球靠近左边缘约1像素，经原生全景与ROI复看仍能看到完整圆周，保留Occluded=0，见[边缘二审](./edge-scene-second-review.json)。几何坐标用于筛查，场景由实际画面确定。
- 调整320张的场景分类。89张重点复查：5张需人工补框/修框、71张需确认可见性，另13张保留尺度、软边或模糊等场景疑点。清单为`../batches/batch-006-priority.txt`。
- **本批1000张球框、场景两项全部仍待用户复查，自动通过0张。**

| 场景 | 图片数（可重叠） |
| --- | ---: |
| 小目标 | 255 |
| 遮挡（含边缘截断） | 187 |
| 运动模糊 | 80 |
| 无球（最终空label口径） | 546 |

逐图理由见[precheck.csv](./precheck.csv)，完整提案与实际证据见[proposals.json](./proposals.json)。

## 人工复查

1000张已固定为20组，每组50张，包含全部89张重点复查项，同帧左右目保持同组，名单不随审核进度移动。

```bash
/home/misaka/workspace/script/review_football_batch.sh 6 --group 1
```

顶部“前50张 / 后50张”翻页，点问题图片修改，保存后按G返回。只显示为1的中文场景名称。组号可换2–20，`6 --groups`显示每组审核进度。

## 备份与校验

[应用备份](/home/misaka/workspace/dataset_processing/batch-review-20261016/applied/20261016T100325Z-37276653)保存原metadata与本批1000份旧label；[独立核验](/home/misaka/workspace/dataset_processing/batch-review-20261016/applied/20261016T100325Z-37276653/verification.json)核对批外7398条CSV原始记录及换行、前5批5000张已审核状态、本批双项待审、原图/旧label备份SHA、20份替换字节与No Ball/最终框数一致性。split、来源、历史计数字段、未知列及旧备注前缀保留。写入在Qt相同QLockFile保护下重核全部字段及图片/label SHA。

Qt6.8.3真实1000张名单的分页、点击返回、中文分类及浏览不自动通过检查已通过，见[smoke.json](/home/misaka/workspace/dataset_processing/batch-review-20261016/batch-006-fixed-groups-ui/smoke.json)；检查前后metadata SHA保持。

## 用户完成复查

2026-10-19，用户确认本批已完成。按本次人工修改后的原图、label与四分类原样保留，1000张球框及场景双项标为已审核：446张有效标注、507张确认无球、47张已审核暂不训练（44张原不确定处置、3张No Ball为1但label非空）。批准只修改状态、两项审核标志与追加备注，不覆盖用户修改。

[独立批准核验](/home/misaka/workspace/dataset_processing/batch-review-20261016/batch-006-approved/REPORT.md)通过；累计6000张完成、2398张待审。上文为助手预审时的历史统计，最终结果以本节和批准快照为准。
