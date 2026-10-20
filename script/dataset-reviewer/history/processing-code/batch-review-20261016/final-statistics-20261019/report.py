"""Reconcile two independent censuses and write the project statistics report."""
import hashlib
import json
from pathlib import Path

W = Path(__file__).resolve().parent
a = json.loads((W/'statistics.json').read_text())
b = json.loads((W/'independent-statistics.json').read_text())
o = a['overall']
checks = {}
def check(name, yes):
    assert yes, name
    checks[name] = True
check('metadata_sha256',a['metadata_sha256']==b['metadata_sha256'])
for left,right in [('total','total'),('usable','trainable'),('reviewed_excluded','reviewed_excluded'),
                   ('pending','pending_any_review_flag'),('usable_positive','positive'),
                   ('usable_negative','confirmed_negative'),('boxes_usable','trainable_boxes'),
                   ('all_zero','all_four_flags_zero'),('all_zero_usable','trainable_all_four_flags_zero'),
                   ('flags_all','flags_all'),('flags_usable','flags_trainable'),
                   ('statuses','status')]:
    check(left,o[left]==b[right])
for split in ('train','val','test'):
    for left,right in [('total','total'),('usable','trainable'),('reviewed_excluded','reviewed_excluded'),
                       ('usable_positive','positive'),('usable_negative','confirmed_negative'),
                       ('boxes_usable','trainable_boxes'),('flags_all','flags_all'),('flags_usable','flags_trainable')]:
        check(split+'_'+left,a['splits'][split][left]==b['split'][split][right])
check('full_image_decode',b['image_validation']['decoded']==o['total'] and not b['image_validation']['errors'])
check('label_validity',a['quality']['invalid_labels']==b['label_validation']['invalid']==4)
check('all_reviews_completed',b['both_reviewed']==o['total'] and o['pending']==0)
check('usable_partition',o['usable']==o['usable_positive']+o['usable_negative'])
check('total_partition',o['total']==o['usable']+o['reviewed_excluded'])
check('all_invalid_labels_already_excluded',all(r['status']=='reviewed_excluded' for r in b['label_validation']['errors']))
check('actual_metadata_still_matches',hashlib.sha256(Path(a['dataset'],'metadata.csv').read_bytes()).hexdigest()==a['metadata_sha256'])
verify=dict(success=True,status='PASS',checks=checks,canonical_dataset_written=False,
            metadata_sha256=a['metadata_sha256'],primary_statistics_sha256=hashlib.sha256((W/'statistics.json').read_bytes()).hexdigest(),
            independent_statistics_sha256=hashlib.sha256((W/'independent-statistics.json').read_bytes()).hexdigest())
(W/'verification.json').write_text(json.dumps(verify,ensure_ascii=False,indent=2)+'\n')

names={'train':'训练集 train','val':'验证集 val','test':'测试集 test'}
flags={'Small':'远距离小目标 Small','Occluded':'明确遮挡（含画边截断）Occluded',
       'Blurred':'运动模糊 Blurred','No Ball':'无球 No Ball'}
t=f'''# 足球数据集最终统计

统计日期：2026-10-19。最后398张已按用户确认完成球框、场景双项审核。本报告来自当前实际 metadata、全部图片和label文件；两套独立统计交叉一致，全部图片已完整解码检查。

## 总体

- 总图片 **{o['total']}** 张，双项审核完成{o['total']}张，待审{o['pending']}张。
- 当前可用 **{o['usable']}** 张：有球{o['usable_positive']}张、确认无球{o['usable_negative']}张。
- **{o['reviewed_excluded']}张已审核但暂不训练**（`reviewed_excluded`），保留为参考；已审核不等于可用。
- 可用样本共{o['boxes_usable']}个足球框；{o['multi_ball_images_usable']}张含两个球，其余有球图均含一个球。
- 四项场景是可重叠的metadata标签，YOLO目标类别仍只有football，不是四个目标类别。

## 按现有split统计

| 集合 | 全部图片 | 当前可用 | 暂不训练 | 可用有球 | 可用无球 | 可用球框 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
'''
for s in ('train','val','test'):
    r=a['splits'][s];t+=f"| {names[s]} | {r['total']} | {r['usable']} | {r['reviewed_excluded']} | {r['usable_positive']} | {r['usable_negative']} | {r['boxes_usable']} |\n"
t+=f"| 合计 | {o['total']} | {o['usable']} | {o['reviewed_excluded']} | {o['usable_positive']} | {o['usable_negative']} | {o['boxes_usable']} |\n"
t+='\n现有分集未移动或重分配。按全部图片占比：'+ '，'.join(f"{names[s]} {a['splits'][s]['total']/o['total']:.2%}" for s in names)+'。\n'
t+='''
## 四项场景

计数单位为图片，一张可同时属于多个场景；不能把四行相加作为总图片数。全0只表示不属于上述四项，不自动决定训练资格。

| 场景 | 全部图片中 | 可用图片中 | 暂不训练图片中 |
| --- | ---: | ---: | ---: |
'''
for k,label in flags.items():t+=f"| {label} | {o['flags_all'][k]} | {o['flags_usable'][k]} | {o['flags_excluded'][k]} |\n"
t+=f"| 四项全为0 | {o['all_zero']} | {o['all_zero_usable']} | {o['all_zero']-o['all_zero_usable']} |\n"
t+='\n全库No Ball为2934张，其中6张已排除；因此当前可用的确认无球样本为2928张。不可将已排除样本的空label直接当作负样本。\n'
for scope,key in [('全部图片','flags_all'),('可用图片','flags_usable')]:
    t+=f'\n### 各集合的场景分布（{scope}）\n\n| 集合 | 小目标 | 遮挡 | 运动模糊 | 无球 |\n| --- | ---: | ---: | ---: | ---: |\n'
    for s in names:t+='| '+names[s]+' | '+' | '.join(str(a['splits'][s][key][k]) for k in flags)+' |\n'
t+='''
## 250张暂不训练样本

按排除前保存的历史处置分组（仅用于解释审核记录，不是再次视觉诊断）：

| 原处置 | 数量 |
| --- | ---: |
'''
reasons={'uncertain':'待定','uncertain_bbox':'球框不确定','severe_blur':'严重模糊',
         'severe_occlusion':'严重遮挡','fully_occluded':'完全遮挡','temporal_only':'仅时序可推断',
         'needs_manual_bbox_annotation':'待人工画框','needs_visibility_review':'待可见性复核',
         'auto_label_needs_review':'原自动标注保留，但不符合可用条件'}
for k,n in sorted(o['excluded_original_status'].items(),key=lambda x:-x[1]):t+=f"| {reasons.get(k,k)} | {n} |\n"
t+='''
这250张中：41张的有效label非空、205张的有效label为空、4份label越界。空框不等于该图已被确认可作负样本，250张均不进入可用统计。原图、label与场景未被本轮统计修改。

## 文件及数据质量

| 检查 | 结果 |
| --- | ---: |
| 实际图片文件 | 8398 |
| 实际label文件 | 8398 |
| 缺图片 / 缺label | 0 / 0 |
| 不在metadata中的孤立图片 / label | 0 / 0 |
| 全部图片完整解码失败 | 0 |
| label几何或格式不规范 | 4（均已排除） |
| 可用样本label错误 / No Ball状态不一致 | 0 / 0 |
| 文件字节完全相同的重复图片（SHA256） | 0组 |

4份越界label（保留原始参考，没有改写）：

'''
for r in b['label_validation']['errors']:t+=f"- `labels/{r['split']}/{Path(r['filename']).stem}.txt`，`reviewed_excluded`。\n"
t+='\n原图分辨率：'+ '，'.join(f'{k}：{n}张' for k,n in o['resolutions'].items())+'。格式：'+ '，'.join(f'{k}：{n}张' for k,n in o['formats'].items())+'。\n'
p=b['provenance_overlap']
t+=f"\n有完整视频/帧号/左右目信息的{p['rows_complete_provenance']}张中，未发现同一原帧（含左右目）跨train/val/test。其余{p['rows_incomplete_provenance']}张缺完整来源信息，无法据此判断。文件SHA查重不能排除重编码、近似图像或相邻帧相似泄漏，本次没有重新执行感知去重或重分集。\n"
t+='''
## 当前训练入口的范围

这250张暂不训练样本仍保存在原始images/labels目录中，未删除或移动。当前dataset.yaml仍指向这些原始目录；后续用于训练、验证和测试的数据应按审核状态过滤为8148张。现有Qt审核工具的“导出完整审核数据集”会按已审核有效标注/确认负样本导出，将reviewed_excluded留作排除参考。

## 统计与审核凭据

- [主统计JSON](./statistics.json)、[独立统计JSON](./independent-statistics.json)、[交叉核验](./verification.json)。
- [250张暂不训练清单](./unusable-images.json)、[标签异常与查重明细](./quality-details.json)。
- [原始metadata快照](./source-metadata.csv)；[全部图片与label扫描清单](./image-inventory.json)。
- [第9批最终批准及独立校验](../batch-009-approved/REPORT.md)。

'''
t+=f"源metadata SHA256：`{a['metadata_sha256']}`。本轮只写最后398张的审核状态和追加确认备注；全部统计扫描不写canonical数据，不调整图片、label、场景或分集。\n"
(W/'REPORT.md').write_text(t)
print(json.dumps(dict(success=True,checks=len(checks),total=o['total'],usable=o['usable'],excluded=o['reviewed_excluded'],report=str(W/'REPORT.md')),ensure_ascii=False))
