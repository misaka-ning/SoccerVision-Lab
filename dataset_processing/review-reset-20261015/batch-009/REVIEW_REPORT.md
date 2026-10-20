# 第9批最后398张预审记录

日期：2026-10-19。**用户已明确确认第9批398张审核完成，球框与场景两项均已标为已审核：344张有效标注、54张确认无球、0张暂不训练。** 以下保留助手预审、候选修框、应用及窗口交接的历史记录；当前最终统计见文末。

## 检查范围和口径

按不可变名单 [batch-009.txt](../batches/batch-009.txt) 检查全部398张。逐页实际查看199张原尺寸全图页及46张旧框ROI页，覆盖全部360个旧框；包含16张多球图片，逐框检查，不只检查第一个球。

沿用既定四分类：完整球约40像素以下作为 Small 候选；明确前景覆盖或真实画边截断标 Occluded；足球或相机存在方向性拖影标 Blurred，单纯软化和脚部运动不自动计入；No Ball 严格按本轮最终候选label是否为空。空label的54张仍待用户确认，不自动通过为负样本。

## 结果

| 项目 | 数量 |
| --- | ---: |
| 图片 | 398 |
| 预审前/候选后足球框 | 360 / 360 |
| 候选修正label | 6 |
| 保留原label字节 | 392 |
| 场景分类有更新建议 | 77 |
| 重点疑点 | 24 |
| 有框 / 空label | 344 / 54 |
| 用户最终批准 | 0 |

四项为多标签，可重叠：Small 64，Occluded 55，Blurred 330，No Ball 54。建议动作：保留380，待可见性复核12，候选修框6。另6张保留框的场景尺度临界项也进入重点疑点，合计24张。

## 六份球框修正

坐标为当前单目原图的 `[x1,y1,x2,y2]`，只框当前可见球体。6份均由主审和root独立查看原像素诊断及前后对比，仍是**待用户复查候选**：

- `video_4bec9c343db72928_frame_00006321_right.png`：`[[51, 198, 164, 279]]`。当前横向白黑运动球右侧拖影超出旧框，候选右移边缘至164覆盖实际可见拖影；仅修可见范围。S0O0B1，运动软界仍人工复查。
- `video_4bec9c343db72928_frame_00012447_left.png`：`[[232, 179, 317, 278]]`。当前可见纵向拖影球上缘被旧框截掉；补齐明亮拖影及深色球面，不包地面软投影。S0O0B1，软边仍待人工复查。
- `video_4bec9c343db72928_frame_00012447_right.png`：`[[191, 178, 274, 279]]`。当前球有明显纵向运动拖影，旧框漏上缘；候选覆盖可见球面及拖影，排除下方地面阴影。S0O0B1，软边待复查。
- `video_4bec9c343db72928_frame_00017403_right.png`：`[[230, 212, 305, 282]]`。旧框仅框左边屏幕矩形亮斑，鞋下当前白黑星纹球明确；移到真实可见球，排除鞋和地面投影。S0O1B1，鞋球软界待复查。
- `video_4bec9c343db72928_frame_00020301_left.png`：`[[632, 117, 672, 253]]`。右边截断的手持星纹球，旧框上/下空区偏大；当前可见球面上沿约117、下沿253，保留当前可见细黑边，不推隐藏全球。S0O1B0，手球软界待人工。 当前球面未见可靠方向性拖影，普通软化不按运动模糊。
- `video_4bec9c343db72928_frame_00020301_right.png`：`[[548, 61, 672, 259]]`。右边截断的手持大球，旧框含上方手臂和下方空区；依据当前白蓝黑面及外轮廓收紧，保持实际可见上/下及左边界。S0O1B0，手部覆盖和软化球边待人工。 当前球面未见可靠方向性拖影，普通软化不按运动模糊。

其中一份原来圈住屏幕矩形亮斑，已在候选中移到该图鞋下真实星纹球；其余修正运动球的截边或手持球框内多余空区。没有可靠的新球补框或整份清空操作。n112/n113右下前景经各自原像素核查为鞋头，未补成第二个球。

## 保留的疑点

见 [precheck.csv](./precheck.csv) 的“重点复查”列和 [24张重点名单](../batches/batch-009-priority.txt)。包含运动软边、鞋球交界、临界小目标、极细底边间隙/截断等。不确定的原框先保留参考；靠近画边不自动当遮挡，靠近鞋不自动当被鞋覆盖。

- [全部逐图建议](./proposals.json)；[统计及输入SHA](./summary.json)。
- [6份候选独立二审](./replacement-second-review.json)。
- [4张边缘场景独立复核](./edge-scene-second-review.json)。
- [第1组134张](./group-1/summary.json)、[第2组132张](./group-2/summary.json)、[第3组132张](./group-3/summary.json)：实际看过的全图/ROI路径与来源SHA均记录。

## 暂存历史与本轮应用

此前第8批审核期间，预审方案仅保存于 [staged](./staged/result.json)，未变更live数据；[暂存独立核验](./staged/verification.json)20项PASS。其 `before`、`proposed`、`preview` 为历史审计材料。**不将历史整份preview CSV覆盖live CSV。**

本轮用户确认第8批完成后，先从新鲜快照将第8批1000张双项批准，再用Qt审核锁和当前CSV合入第9批398张：6份label修正、77张场景更新，360个球框保持总数，0跳过、0失败；其余392份label字节保留。来源、split、历史计数和备注前缀保留，398张仍全部双项待用户复查，前8000张已审核状态保留。

- [实际应用审计](/home/misaka/workspace/dataset_processing/batch-review-20261016/applied/20261019T032342Z-56593226/result.json)。
- 应用后独立核验 **PASS**：[应用后独立核验](/home/misaka/workspace/dataset_processing/batch-review-20261016/applied/20261019T032342Z-56593226/verification.json)；[报告](/home/misaka/workspace/dataset_processing/batch-review-20261016/applied/20261019T032342Z-56593226/REPORT.md)。
- [Qt6.8.3分页交互检查](/home/misaka/workspace/dataset_processing/batch-review-20261016/batch-009-fixed-groups-ui/smoke.json)PASS；真实CSV未被测试编辑，398张全范围、第一页下一页/末页上一页、末页48张、正项中文/零项留空均通过。

## 人工复查

[固定平铺名单](../batches/batch-009-remaining-50/README.md)包含全部398张和24张重点疑点，不排除疑点；每页50张，共8页，末页48张。左右目同帧保持同组。点图修改，保存后按G返回；顶部“前50张/后50张”翻页。平铺浏览本身不自动批准任何图片。

```bash
/home/misaka/workspace/script/review_football_batch.sh 9 --group 1
```

窗口启动状态以 [active-review-window.json](/home/misaka/workspace/dataset_processing/batch-review-20261016/active-review-window.json) 为准。


## 用户完成最后一批审核（2026-10-19）

按用户本轮确认及新鲜快照批准398张，344张reviewed_annotation、54张negative_confirmed、0张reviewed_excluded；仅更新审核状态和追加备注，原图、label与四类场景值保留。[最终批准及独立核验](../../batch-review-20261016/batch-009-approved/REPORT.md)PASS。

全库8398张已全部双项审核完成：可用8148张（5220有球/2928确认无球），250张已审核但暂不训练，待审0张。[最终统计](../../batch-review-20261016/final-statistics-20261019/REPORT.md)。
