#!/usr/bin/env python3
"""Produce traceable current-review reports and verify all canonical assets."""
import argparse, csv, hashlib, json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLAGS = ('Small', 'Occluded', 'Blurred', 'No Ball')
PENDING = {'auto_label_needs_review', 'needs_visibility_review', 'needs_manual_bbox_annotation'}

def pending_label(r):
    return r['label_review_required'] == '1' or r['annotation_status'] in PENDING

def pending_scene(r):
    return r['scene_review_required'] == '1'

def pending(r):
    return pending_label(r) or pending_scene(r)

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write_csv(name, fields, rows):
    with (HERE / name).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

def main():
    p=argparse.ArgumentParser();p.add_argument('--audit',type=Path,required=True);p.add_argument('--dataset',type=Path,default=Path('/home/misaka/workspace/datasets'));a=p.parse_args()
    original=json.loads((HERE/'inventory.json').read_text())
    prior={b['filename']:b['meta'] for b in original}
    decisions={d['filename']:d for d in json.loads((HERE/'combined-decisions.json').read_text())}
    result=json.loads((a.audit/'result.json').read_text())
    applied={r['filename']:r for r in result['applied']}
    with (a.dataset/'metadata.csv').open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
    now={r['图片']:r for r in rows}
    assert len(now)==len(rows)==len(prior)==8398
    assert set(now)==set(prior)
    changes=[];remaining=[];approved=[];asset_changes=[];unexpected_metadata=[]
    counts=Counter()
    for b in original:
        name=b['filename'];old=prior[name];row=now[name]
        for kind in ('image','label'):
            path=b[f'{kind}_path'];actual=digest(path)
            if actual!=b[f'{kind}_sha256']:
                asset_changes.append({'filename':name,'kind':kind,'path':path,'baseline_sha256':b[f'{kind}_sha256'],'current_sha256':actual})
        expected=applied[name]['after_meta'] if name in applied else old
        diff=[k for k,v in expected.items() if row.get(k)!=v]
        if diff:unexpected_metadata.append({'filename':name,'fields':diff,'reason':'审核落盘前后另有修改；不覆盖'})
        if name in applied:
            d=decisions[name]
            counts['positive_label_approvals']+=int(d['label_decision']=='approve_positive')
            counts['negative_label_approvals']+=int(d['label_decision']=='approve_negative')
            counts['scene_approvals']+=int(d['scene_decision']=='approve' and pending_scene(old) and not pending_scene(row))
            flag_diff=[k for k in FLAGS if old[k]!=row[k]]
            counts['scene_corrected_images']+=bool(flag_diff)
            for k in flag_diff:counts[f'corrected_{k}']+=1
            item={'图片':name,'split':row['split'],'球框决定':d['label_decision'],'分类决定':d['scene_decision'],
                  '修改分类':','.join(flag_diff),'审核依据':d['reason'],'labelSHA256':b['label_sha256'],
                  **{f'原{k}':old[k] for k in FLAGS},**{k:row[k] for k in FLAGS}}
            changes.append(item)
        if name in applied and not diff and pending(old) and not pending(row):
            counts['fully_cleared_images']+=1
            approved.append({'图片':name,'split':row['split'],'annotation_status':row['annotation_status'],
                             **{k:row[k] for k in FLAGS},'审核依据':decisions[name]['reason']})
        if pending(row):
            d=decisions.get(name,{})
            remaining.append({'图片':name,'split':row['split'],'annotation_status':row['annotation_status'],
                              '球框待审':int(pending_label(row)),'分类待审':int(pending_scene(row)),
                              **{k:row[k] for k in FLAGS},'本次复核依据':d.get('reason','本次视觉基线之后新增的待审项'),
                              'label_review_note':row['label_review_note']})
            if name in applied and ((pending_label(old) and not pending_label(row)) or (pending_scene(old) and not pending_scene(row))):
                counts['partially_cleared_images']+=1
    raw=(a.dataset/'metadata.csv').read_bytes()
    yaml_unchanged=(a.dataset/'dataset.yaml').read_bytes()==(HERE/'baseline/dataset.yaml').read_bytes()
    total_before=sum(pending(r) for r in prior.values())
    total_after=sum(pending(r) for r in rows)
    output={'dataset_images':len(rows),'dataset_labels':len(original),'pending_before':total_before,'pending_after':total_after,
            'label_pending_before':sum(pending_label(r) for r in prior.values()),'label_pending_after':sum(pending_label(r) for r in rows),
            'scene_pending_before':sum(pending_scene(r) for r in prior.values()),'scene_pending_after':sum(pending_scene(r) for r in rows),
            **dict(counts),'applied_metadata_rows':len(applied),'skipped':result['skipped'],
            'canonical_asset_changes':asset_changes,'post_baseline_metadata_changes':unexpected_metadata,
            'dataset_yaml_unchanged':yaml_unchanged,'csv_bom_preserved':raw.startswith(b'\xef\xbb\xbf'),
            'csv_fields':fields,'metadata_sha256':hashlib.sha256(raw).hexdigest(),'application_audit':str(a.audit)}
    (HERE/'final-review-summary.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    write_csv('all-reviewed.csv',['图片','split','球框决定','分类决定','修改分类',*[f'原{k}' for k in FLAGS],*FLAGS,'审核依据','labelSHA256'],changes)
    write_csv('approved.csv',['图片','split','annotation_status',*FLAGS,'审核依据'],approved)
    write_csv('remaining-review.csv',['图片','split','annotation_status','球框待审','分类待审',*FLAGS,'本次复核依据','label_review_note'],remaining)
    report=f'''# 未审核样本复核记录（2026-10-14）

本次按用户“置信度比较高的直接通过、不确定的保留”的明确授权，对当时待审核的全部 **{total_before:,} 张**图片逐张检查全景，并检查每个现有候选球框。空 label 通过原生图像复核，特别检查下边缘小球、机器人/人物脚部以及灰暗足球。通过依据是实际画面和框的贴合程度，没有用模型分数替代视觉审核。

## 结果

| 项目 | 数量 |
|---|---:|
| 数据集图片/对应 label | {len(rows):,} / {len(original):,} |
| 本次完全通过（球框和分类均无需再审） | {counts['fully_cleared_images']:,} |
| 仅通过其中一项、另一项仍待审 | {counts['partially_cleared_images']:,} |
| 新通过有球 label | {counts['positive_label_approvals']:,} |
| 新通过空 label / 无球样本 | {counts['negative_label_approvals']:,} |
| 新通过场景分类 | {counts['scene_approvals']:,} |
| 修正了明确场景分类的图片 | {counts['scene_corrected_images']:,} |
| 当前仍有至少一项待审 | {total_after:,} |
| 当前球框待审 / 场景待审 | {output['label_pending_after']:,} / {output['scene_pending_after']:,} |

球框与分类独立判断，因此数量不能直接相加。当框可靠但 Small 尺寸接近临界线或遮挡边界不明确时，只通过球框，分类继续保留。已经由用户确认的 label 不重新修改其审核状态。

## 判定标准

- 正样本：能确认足球本体、可见目标没有漏框/重复框，框的四条边贴合外轮廓，没有明显大片背景或把阴影并入球框。矩形四角的正常背景不当成框松散。
- 负样本：原生画面中确实无可见足球，且 label 是零字节文件；空检测或空 label 本身不作为无球证据。
- Small：原图长边归一到 672 后，完整足球最长边约不超过 40 像素；约 40 像素及无法估计完整球体大小的情况保留分类待审。
- Occluded：有明确前景物体遮挡足球，包括手、鞋、腿、机器人等；仅触碰或画面裁边不作为遮挡。
- Blurred：足球或整幅图像有实际运动拖影；小目标低分辨率不直接等同运动模糊。
- No Ball：只有视觉确认无球才置 1；有球的普通样本四项均为 0 也是有效分类。

仍待审的主要情况包括：空 label 的底边漏球、白脚/脚轮误框、框含过多阴影或背景、球体严重拖影、遮挡外沿难以确认、Small 尺寸临界等。每张的原因见 `remaining-review.csv`。

## 写入和保护

本次只写 `metadata.csv` 的分类、审核状态及原因；正式图片、label、split 和 `dataset.yaml` 不由本次程序改写。通过行记录“用户授权助手视觉复核”，不把它描述为用户逐张手工确认。来源计数及未知 CSV 列保留。

写入前检查图像/label SHA256 和原 metadata 字段，保护审核工具中的新修改；使用原生 Qt `QLockFile` 与审核工具协调，CSV 一次原子保存。保存前完整备份位于 `{a.audit / 'before/metadata.csv'}`。

正式图片与 label 相对视觉基线改变数：{len(asset_changes)}。`dataset.yaml` 保持一致：{yaml_unchanged}。保存时跳过记录：{len(result['skipped'])}。

## 交付文件

- `approved.csv`：本次完全通过的图片。
- `all-reviewed.csv`：全部实际写入的复核决定，含原分类、新分类及依据。
- `remaining-review.csv`：当前所有仍待审图片与具体原因。
- `visual-coverage.json`：三组全景、球框、原生核实的覆盖记录。
- `final-review-summary.json`：数量、文件一致性、写入审计位置。
- `validation-after.json`：规范化数据校验结果；待审警告不代表已通过视觉审核。

审核工具重新载入数据集即可读取本次状态：

```bash
/home/misaka/workspace/script/dataset-reviewer/review_dataset.sh --dataset /home/misaka/workspace/datasets
```
'''
    (HERE/'审核说明.md').write_text(report)
    print(json.dumps({k:v for k,v in output.items() if k not in {'csv_fields','skipped','canonical_asset_changes','post_baseline_metadata_changes'}},ensure_ascii=False,indent=2))
    if not yaml_unchanged:raise SystemExit('dataset.yaml changed outside review')

if __name__=='__main__':main()
