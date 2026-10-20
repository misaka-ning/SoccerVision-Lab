# 第8批足球数据集预审记录

日期：2026-10-19。正式数据集：`/home/misaka/workspace/datasets`。

固定名单 `../batches/batch-008.txt` 共1000张，`video_4bec9c343db72928_frame_00020296_left.png` 至 `video_4bec9c343db72928_frame_00024119_right.png`。图像、来源与train/val/test划分保留。

## 本批口径

延续用户第5批起的[审核说明](/home/misaka/workspace/dataset_processing/batch-review-20261016/REVIEW_POLICY.md)：足球被画面边缘截断（包括半球）和明确前景覆盖均标Occluded=1；鞋只靠近或接触而未覆盖不自动算遮挡。No Ball严格按最终label计数：零框为1，有框为0。身份或边界待查且没有可靠框的图片仍标No Ball=1，同时保持待审及具体疑点；不自动成为已确认无球训练样本。

Small按完整球尺度折算到图像长边672后约40像素判断，大球残片不因可见部分小而算小目标。Blurred要求球或相机有方向拖影，不把低像素软化、失焦或单独人体/脚部移动直接算运动模糊。四项可重叠，不属于时全0。已人工审核的前7批保留用户结果。

## 预审结果

- 实际逐幅查看1000张原生全景及619个旧框，证据为500页全景和78页旧框局部对照，另有原生坐标网格和前后对照。group4由0–75、76–125、126–249三个连续分段独立检查后合并，完整覆盖250张。
- **9份label变更**：5张原空label补球候选；2份底边运动球旧框上扩，补回原框切漏的当前可见球面；2份手持球旧框收紧左侧，剔除多余手臂。球框619→624，未清空旧label。
- 9项均由第二位审核者实际复看当前原图/原生网格和候选对照，最终坐标与[二审记录](./replacement-second-review.json)一一对应。新框只取当前可见部分，不推隐藏全球；强拖影、鞋球交界及极薄球冠继续列为不确定候选，交用户确认。
- 269张更新场景分类。**22张重点复查**：9份改框候选、6张人工补框或精修、7张确认身份/可见性。无法判清的鞋球上边界保留旧框，未强行扩入鞋尖；没有可靠框的疑似球仍按空label口径记No Ball=1。
- 对靠边但Occluded=0的9张额外复看原生全景与ROI：均可见球下弧及图内间隙，保留0，见[边缘二审](./edge-scene-second-review.json)。几何靠边本身不等于裁切。
- 后段固定看向玩偶、陈列架的空帧也逐张查看，玩偶圆头、黑白衣裤印花、人体经过与遮住镜头均未直接当足球或足球遮挡。
- **1000张球框、场景均仍待用户复查，自动通过0张。** 全库8398张，已审核7000张，待审1398张；当前1000张之外尚有最后398张。

| 场景 | 图片数（可重叠） |
| --- | ---: |
| 小目标 | 76 |
| 遮挡（含边缘截断） | 127 |
| 运动模糊 | 286 |
| 无球（最终空label） | 376 |

624张非空label均No Ball=0；376张空label均No Ball=1。逐图建议、分类及理由见[precheck.csv](./precheck.csv)，完整提案和证据见[proposals.json](./proposals.json)。重点名单为 `../batches/batch-008-priority.txt`。

## 每页50张复查

本批固定20页，每页50张，包含全部22张疑点；同帧左右目保持同页，名单不随审核进度移动。

```bash
/home/misaka/workspace/script/review_football_batch.sh 8 --group 1
```

顶部“前50张 / 后50张”翻页；点图修改，保存后按G返回平铺。只显示为1的中文场景，0留空。组号可改2–20；`8 --groups`查看每组进度。浏览不会自动通过图片。

## 备份与验证

[应用审计与备份](/home/misaka/workspace/dataset_processing/batch-review-20261016/applied/20261019T030103Z-91bc5e78)保存写入前metadata、本批1000份旧label、9份拟替换label以及基线/提案。写入在与Qt相同的QLockFile下重核全部metadata字段及图片/label SHA；跳过0张、失败0张。

[独立核验](/home/misaka/workspace/dataset_processing/batch-review-20261016/applied/20261019T030103Z-91bc5e78/verification.json)核对1000张原图和旧标注备份、991份未变label、9份替换字节与二审、批外7398条原始CSV及换行/BOM/顺序、前7000张已审核状态、来源/split/历史计数/未知列/旧注记前缀、双待审及No Ball关系。独立核验结果为 **PASS**；当前1000张仍双待审，前7000张已审核状态保留。

Qt6.8.3真实1000张分页和交互检查已通过，记录：[smoke.json](/home/misaka/workspace/dataset_processing/batch-review-20261016/batch-008-fixed-groups-ui/smoke.json)。测试使用独立编辑夹具，真实metadata只读；正式预审后SHA为 `e7ad9bc05e5b386efd39e0a0b86ee8710da75946998c5bcbe3e1a8bd83887772`。


## 用户完成第8批人工审核（2026-10-19）

用户明确确认本批已审完。按本轮新鲜快照将1000张球框和场景两项均标为已审核：624张有效标注、376张确认无球、0张暂不训练；保留原图、label和四类分类，只更改审核状态并追加确认备注。累计完成8000张，最后398张仍待用户复查。

[批准及独立校验报告](/home/misaka/workspace/dataset_processing/batch-review-20261016/batch-008-approved/REPORT.md)；[verification.json](/home/misaka/workspace/dataset_processing/batch-review-20261016/batch-008-approved/verification.json)。
