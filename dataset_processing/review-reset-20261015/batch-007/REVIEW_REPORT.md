# 第7批足球数据集预审记录

日期：2026-10-19。正式数据集：`/home/misaka/workspace/datasets`。

固定名单 `../batches/batch-007.txt` 共1000张，`video_4bec9c343db72928_frame_00016542_left.png` 至 `video_4bec9c343db72928_frame_00020294_right.png`。原图、来源和train/val/test划分保留。

## 审核口径

延续用户第5批开始的[审核说明](/home/misaka/workspace/dataset_processing/batch-review-20261016/REVIEW_POLICY.md)：真实前景遮挡、球被画面边缘截断（包括半球）均标Occluded=1；鞋仅接近或接触球而未覆盖，不自动算遮挡。No Ball按最终label计数：零框为1，有球框为0。身份/边界待查而尚无可靠框的图片仍标No Ball=1，同时保留待审核及具体疑点，不自动成为已确认无球训练样本。

Small按完整球尺度折算图像长边672后约40像素判断，不把大球残片当小目标；临界尺度保留疑点。Blurred要求球或相机有可辨方向拖影，低像素软化、失焦或仅脚部运动不自动计入。四类可重叠，均不属于时全0。前6批用户审核结果保留。

## 预审结果

- 逐幅实际查看1000张原生全景和666个旧框，证据为500页全景、84页原生旧框对照，另有坐标网格、放大及前后对照。
- **16份label变更**：9张原空label补足球候选；7份旧框修正，包含剔除鞋面、去掉长投影、补回被旧框切漏的可见球面以及补回底边当前球冠。框数666→675，未清空旧label。
- 全部16项通过第二位审核者的原生视觉复看；最终提案坐标与[二审记录](./replacement-second-review.json)逐项一致。group4的2处修框由另一位审核者独立核边，再由主审核者查看最终对照，见[独立记录](./group-4/root-candidates-independent-review.json)。这些均是待用户复核的候选，不是最终通过。
- group4的2个底边强拖影粗补框撤回：当前软边不稳定，试框还会切漏局部，不强写坐标。保持空label及人工补框疑点，见[撤回记录](./withdrawn-candidates.json)。
- 285张更新场景分类。**89张重点复查**：21张确认身份/可见性、8张人工补框或精修，其余60张保留软边、鞋球交界、模糊或Small临界等疑点；清单为 `../batches/batch-007-priority.txt`。
- 全部1000张球框及场景仍双项待用户复查，自动通过0张。全库8398张，前6批已审核6000张，待审核2398张。

| 场景 | 图片数（可重叠） |
| --- | ---: |
| 小目标 | 64 |
| 遮挡（含边缘截断） | 217 |
| 运动模糊 | 324 |
| 无球（最终空label口径） | 325 |

675张非空label均No Ball=0，325张空label均No Ball=1。靠边几何仅作筛查：3张距底边约2至3像素的球经原生全景/ROI仍见完整下弧，保留Occluded=0；另复看16张旧分类为0的截断球并确认应为1，见[边缘二审](./edge-scene-second-review.json)。

逐图理由见[precheck.csv](./precheck.csv)，完整待审提案和证据见[proposals.json](./proposals.json)。

## 每页50张复查

1000张固定为20页，每页50张，包含全部89张疑点；同帧左右目保持同页，名单不随审核进度移动。

```bash
/home/misaka/workspace/script/review_football_batch.sh 7 --group 1
```

顶部“前50张 / 后50张”翻页，点问题图片编辑，保存后按G返回平铺。只显示为1的中文分类，0不显示。组号可改为2–20；`7 --groups`查看每组进度。浏览平铺不会自动通过图片。

## 备份与验证

[应用审计与备份](/home/misaka/workspace/dataset_processing/batch-review-20261016/applied/20261019T022722Z-e11a7a5f)保存批准后原metadata、本批1000份原label、16份拟替换label及完整提案/基线。正式写入在与Qt相同的QLockFile保护下，重新核对所有metadata字段及图片/label SHA；跳过0张、写入失败0张。

[独立核验结果](/home/misaka/workspace/dataset_processing/batch-review-20261016/applied/20261019T022722Z-e11a7a5f/verification.json)核对原图、旧框备份、984份未变label与16份最终替换、批外7398条原始CSV及换行/BOM/顺序、前6000张已审核状态、来源/split/历史计数/未知列/旧备注前缀、双待审状态、实际证据和最终框数与No Ball关系。独立核验结果为 **PASS**；1000张仍双项待审，前6000张状态保留。

Qt6.8.3使用真实1000张名单验证50张分页、末页返回、点击保存后返回、中文正类显示和浏览不自动通过，见[smoke.json](/home/misaka/workspace/dataset_processing/batch-review-20261016/batch-007-fixed-groups-ui/smoke.json)。真实metadata未被测试修改，检查后SHA仍为 `8088931728470c0cc03d7af61824f4ce0f3d046d97ba02062fc656087983339d`。

## 用户完成复查

2026-10-19，用户确认本批已完成。保留本次人工检查后的原图、label及四分类，1000张球框与场景双项标为已审核：675张有效标注、325张确认无球、0张暂不训练。批准仅更新状态、双项审核标志及追加备注。

[批准独立核验](/home/misaka/workspace/dataset_processing/batch-review-20261016/batch-007-approved/REPORT.md)通过，累计完成7000张、待审1398张。上文为助手预审的历史记录，最终批准以本节及用户完成快照为准。
