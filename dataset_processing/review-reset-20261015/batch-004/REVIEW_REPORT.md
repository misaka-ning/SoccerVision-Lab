# 第4批足球数据集预审记录

日期：2026-10-16。正式数据集：`/home/misaka/workspace/datasets`。

本批使用固定名单`../batches/batch-004.txt`，共1000张，从`video_4bec9c343db72928_frame_00005020_left.png`到`video_4bec9c343db72928_frame_00008812_right.png`。没有增删原图或调整train/val/test。

## 预审结果

- 逐幅检查1000张原生全景和797个原有框；证据为500页原生全景及101页原框局部对照，并单独放大遗漏或遮挡疑点。
- 修改20份label：16份原空label补上候选；2份已有框的图片各补1个漏球；2份修正旧框上沿漏球或下沿包含阴影的问题。共增加18个球框，框数797→815。20份替换方案均做原生前后对照和第二遍审阅，框只采用当前可见范围。
- 调整333张的四类场景值；四项可以重叠，没有对应场景时全部为0。
- 13张需要人工补框/修框，85张需要确认球是否可见。重点复查清单共463张，其中435张不确定，另外28张为高把握的无球候选，沿用待确认可见性状态并纳入重点清单。疑点包含球尺度临界、遮挡接触关系与模糊边界。
- 疑似球或已可辨球但不能可靠画框时保持No Ball=0；机械反光、鞋和空label不能单独作为无球依据。未解决的旧框留作参考，继续待人工处理。
- **本批1000张的label与场景全部保留待用户复查，自动通过0张。**

| 场景 | 图片数（可重叠） |
| --- | ---: |
| 小目标 | 331 |
| 遮挡 | 111 |
| 运动模糊 | 233 |
| 无球候选 | 201 |

## 人工复查

全部1000张固定为20组，每组50张，包含全部463张重点复查项，同帧左右目保持同组，名单不随审核进度变化。

```bash
/home/misaka/workspace/script/review_football_batch.sh 4 --group 1
```

顶部“前50张 / 后50张”翻页；点击问题图片修改，保存后按G返回。只显示值为1的中文场景名称，其他留空。把组号换为2–20可从指定组继续，`4 --groups`查看各组审核进度。

逐图理由见[precheck.csv](./precheck.csv)，全量提案和证据路径见[proposals.json](./proposals.json)，疑点名单为`../batches/batch-004-priority.txt`。

## 判定口径

Small按完整球尺度折算到图像长边672后约40像素判断，大球的小残片不算小目标。Occluded包含明确的鞋、手、人体或机器人等前景遮挡，单纯接触与画面裁切不自动算。Blurred要求球体或相机有可辨方向性运动拖影，低像素软化和仅鞋移动不自动算。No Ball逐图判断，不用另一目或相邻帧替代当前图可见性。

本批重点处理墙脚远小球、底边截断球及机器人腿/手边露出的球。球体身份或精确边界不可靠的保留人工补框/可见性疑点，未因空label直接判断无球。

## 备份与校验

[应用备份](/home/misaka/workspace/dataset_processing/batch-review-20261016/applied/20261016T083334Z-1886789c)保留原metadata和本批1000份旧label；[独立校验](/home/misaka/workspace/dataset_processing/batch-review-20261016/applied/20261016T083334Z-1886789c/verification.json)核对批外7398条CSV原记录及换行、前三批3000张已审核状态、本批双项待审状态、原图SHA和20份label替换。split、来源、计数字段、未知字段与已有备注保持。写入前在Qt相同文件锁下比较全部metadata字段及图片/label SHA。

Qt6.8.3的1000张真实名单分页、点击返回与只浏览不通过检查已通过，见[smoke.json](/home/misaka/workspace/dataset_processing/batch-review-20261016/batch-004-fixed-groups-ui/smoke.json)；metadata在检查前后SHA相同。

## 后续人工审核状态（2026-10-16）

用户已确认本批1000张的label和场景全部复查完成，现均为双项已审核：725张有效标注、234张确认无球、41张已审核但暂不训练。保留用户修改后的label及四类分类；以上预审统计为当时历史记录。见[批准及独立校验记录](/home/misaka/workspace/dataset_processing/batch-review-20261016/batch-004-approved/REPORT.md)。后续第5批起的新场景口径见[审核说明](/home/misaka/workspace/dataset_processing/batch-review-20261016/REVIEW_POLICY.md)。
