# 第5批足球数据集预审记录

日期：2026-10-16。正式数据集：`/home/misaka/workspace/datasets`。

固定名单`../batches/batch-005.txt`共1000张，`video_4bec9c343db72928_frame_00008816_left.png`至`video_4bec9c343db72928_frame_00012677_right.png`。原图、来源和train/val/test划分保持。

## 本批采用的新口径

依据用户本轮指示，从第5批及后续批次开始：

- 足球被画面边缘截断，包括只露半个球，也记遮挡Occluded=1。明确的手、鞋、腿、机器人或器材遮挡继续记1；只是贴近未覆盖不算。
- **No Ball按最终label判定：无框为1，有框为0。** 本批524张空label均标无球，476张有框均为0；可辨但未能可靠定位、仍保留空label的人工补框项同样按用户口径标1，并在理由中记录疑点。此字段不自动通过审核。
- Small按完整球尺度折算至长边672后约40像素判断，大球残片不算小目标。Blurred需可辨方向性球/相机拖影，低像素软化或仅脚移动不自动算。

[完整审核说明](/home/misaka/workspace/dataset_processing/batch-review-20261016/REVIEW_POLICY.md)及[机器配置](/home/misaka/workspace/dataset_processing/batch-review-20261016/review-policy.json)已保存；前4批已审核结果不追溯改写。

## 预审结果

- 逐图实际查看1000幅原生全景与478个原有球框，证据为500页原生全景、61页原框局部对照；另有疑点原生裁切、网格与前后对照。
- 34份label变更：16张原空label补足球候选；18张机器人脚/腿外壳、人物鞋面及鞋带误框删除。框总数478→476。全部34项都经过第二遍原生对照核验，见[二审记录](./replacement-second-review.json)。新框只取当前可见球面，不推测遮挡部分。
- 漏球包含地面远小球、画面上/下边缘残球、机器人遮挡球及器材架后露出的半球。两张底边球的上沿经二审再收紧，排除背景灰晕或鞋影。
- 调整381张的四项分类。12张低像素小球难区分软化与运动拖影，Blurred暂0并保留场景疑点。
- 共82张重点复查：37张需要人工补框/修框，33张需要确认可见性，另外12张需确认模糊分类。全量疑点为`../batches/batch-005-priority.txt`。
- **全部1000张label和场景两项仍为待用户复查，自动通过0张。**

| 场景 | 图片数（可重叠） |
| --- | ---: |
| 小目标 | 261 |
| 遮挡（含画面边缘截断） | 142 |
| 运动模糊 | 168 |
| 无球（最终空label口径） | 524 |

逐图建议与理由见[precheck.csv](./precheck.csv)，完整提案及实际证据路径见[proposals.json](./proposals.json)。

## 人工复查

1000张已固定为20组，每组50张，包含全部82张重点复查项，同帧左右目保持同组。名单不随审核进度改变。

```bash
/home/misaka/workspace/script/review_football_batch.sh 5 --group 1
```

顶部“前50张 / 后50张”翻页。点击问题图片修改，保存后按G返回；只显示值为1的中文场景名称，其他留空。组号可换2–20，`5 --groups`显示分组审核进度。

## 备份与校验

[应用备份](/home/misaka/workspace/dataset_processing/batch-review-20261016/applied/20261016T092429Z-ead2e5bb)含原metadata和本批1000份旧label；[独立核验](/home/misaka/workspace/dataset_processing/batch-review-20261016/applied/20261016T092429Z-ead2e5bb/verification.json)核对批外7398条CSV原始记录/换行、前4批4000张已审核状态、本批双项待审、原图/label备份SHA、34份替换字节与No Ball/框数一致性。split、来源、历史计数字段、未知字段与旧备注前缀保留。写入前在Qt相同QLockFile保护下重核全部metadata字段及图片/label SHA。

Qt6.8.3的真实1000张分页、点击返回、中文分类及浏览不自动审核检查通过，见[smoke.json](/home/misaka/workspace/dataset_processing/batch-review-20261016/batch-005-fixed-groups-ui/smoke.json)；检查前后metadata SHA相同。

## 后续人工审核状态（2026-10-16）

用户已确认本批1000张的球框和场景全部复查完成，均为双项已审核：498张有效标注、488张按用户最终标注确认无球、14张保留原不确定处置且已审核暂不训练。保留用户修改后的图、label和四项分类；以上预审统计保留为历史记录。见[批准与独立校验记录](/home/misaka/workspace/dataset_processing/batch-review-20261016/batch-005-approved/REPORT.md)。
