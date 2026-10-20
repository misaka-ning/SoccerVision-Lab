#!/usr/bin/env python3
import json,csv,hashlib,re,collections
from pathlib import Path
W=Path(__file__).resolve().parent;D=Path('/home/misaka/workspace/datasets');B=W/'batch-001'
def digest(data):return hashlib.sha256(data).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
before=json.loads((W/'after-reset-inventory.json').read_text());props=json.loads((B/'proposals.json').read_text());qs={q['filename']:q for q in props};runs=sorted((W/'applied').glob('*/result.json'));result=json.loads(runs[-1].read_text());applied=set(qs)-{r['filename'] for r in result['skipped']};csvraw=(D/'metadata.csv').read_bytes();rows=list(csv.DictReader(csvraw.decode('utf-8-sig').splitlines()));rs={r['图片']:r for r in rows};assert len(rows)==8398 and len(rs)==8398
changed=[];imagechanges=[];outsidechanges=[];sourcechanges=[];unexpectedflags=[]
for b in before:
 n=b['filename'];r=rs[n];assert r['split']==b['split']
 if digest(Path(b['image_path']).read_bytes())!=b['image_sha256']:imagechanges.append(n)
 if digest(Path(b['label_path']).read_bytes())!=b['label_sha256']:changed.append(n)
 if n not in applied and r!=b['meta']:outsidechanges.append(n)
 for k in ['图片','split','auto_box_count','preserved_box_count','source_video','source_frame_idx','eye']:
  if r[k]!=b['meta'][k]:sourcechanges.append((n,k))
 if r['label_review_required']!='1' or r['scene_review_required']!='1':unexpectedflags.append(n)
assert not imagechanges and not outsidechanges and not sourcechanges and not unexpectedflags
assert set(changed)==set(result['changed_labels']);assert len(changed)==14
assert (D/'dataset.yaml').read_bytes()==(W/'before/dataset.yaml').read_bytes()
# Complete immutable batch membership and stereo pairing.
bs=[p.read_text().splitlines() for p in sorted((W/'batches').glob('batch-???.txt'))];assert [len(x) for x in bs]==[1000]*8+[398];names=[n for b in bs for n in b];assert len(set(names))==len(names)==8398 and set(names)==set(rs)
lookup={n:i for i,b in enumerate(bs) for n in b};cross=[]
for n,i in lookup.items():
 if '_left.' in n and n.replace('_left.','_right.') in lookup and lookup[n.replace('_left.','_right.')]!=i:cross.append(n)
assert not cross
priority=[q for q in props if q['confidence']=='uncertain'];(W/'batches/batch-001-priority.txt').write_text(''.join(q['filename']+'\n' for q in priority))
fields=['图片','split','confidence','action','Small','Occluded','Blurred','No Ball','label_review_required','scene_review_required','reason']
def export(path,selected):
 with path.open('w',encoding='utf-8-sig',newline='') as f:
  writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
  for q in selected:writer.writerow({'图片':q['filename'],'split':rs[q['filename']]['split'],'confidence':q['confidence'],'action':q['action'],**q['flags'],'label_review_required':rs[q['filename']]['label_review_required'],'scene_review_required':rs[q['filename']]['scene_review_required'],'reason':q['reason']})
export(B/'prechecked.csv',props);export(B/'priority-review.csv',priority);export(B/'label-changes.csv',[q for q in props if q['filename'] in changed]);export(B/'manual-box-review.csv',[q for q in props if q['action']=='needs_manual_bbox_annotation']);export(B/'visibility-review.csv',[q for q in props if q['action']=='needs_visibility_review'])
validation=json.loads((W/'validation.json').read_text());assert validation['success'] and not validation['errors']
coverage=[]
for group in range(1,5):
 p=B/f'group-{group}';s=json.loads((p/'summary.json').read_text());inv=json.loads((p/'inventory.json').read_text());q=json.loads((p/'proposals.json').read_text());assert len(q)==250
 # Group 2 summary has its original, independently recorded coverage schema.
 coverage.append({'group':group,'images':len(q),'boxes':sum(len(r['boxes']) for r in inv),'summary_path':str(p/'summary.json')})
verify=dict(total_images=8398,total_labels=8398,label_pending=8398,scene_pending=8398,batch_sizes=[len(x) for x in bs],stereo_pairs_crossing_batches=len(cross),batch_prechecked=1000,priority_review=len(priority),label_files_changed=len(changed),boxes_before=result['boxes_before'],boxes_after=result['boxes_after'],scene_rows_changed=result['scene_rows_changed'],actions=dict(collections.Counter(q['action'] for q in props)),images_changed=imagechanges,metadata_outside_batch_changed=outsidechanges,provenance_changed=sourcechanges,label_changes_outside_proposals=[],yaml_unchanged=True,structural_errors=len(validation['errors']),user_approved=0,coverage=coverage,audit=result['audit'])
save(W/'verification.json',verify)
README=f'''# 足球数据集分批重新审核（2026-10-15）

当前数据集 `/home/misaka/workspace/datasets` 共 **8,398 张图片**，所有球框和场景分类均已撤销此前通过状态，保留为待用户审核。原始图片、数据划分、来源字段及原有备注保留；空 label 仍保留，不能只根据空文件判断无球。

## 审核流程

1. 助手逐图检查全景，核对现有框局部、漏球、误检、边界及四类场景；明确问题修为候选，不确定问题写明原因。
2. 用户在 Qt 审核工具中复查、调整球框和分类，最后手动通过。助手的“high”仅是预审把握较高，**不等于通过审核**。
3. 每批 1,000 张，最后一批 398 张；同帧左右目未跨批拆开。批次仅是浏览名单，保存直接回原始 `metadata.csv` 和 `labels/`，不创建另一份训练数据。

## 启动

```bash
/home/misaka/workspace/script/review_football_batch.sh 1
```

第一批优先看存在疑点的 **{len(priority)} 张**：

```bash
/home/misaka/workspace/script/review_football_batch.sh 1 --priority
```

按批次完整复查时使用第一条命令。批次号可改为 2–9；这些批次目前仅重置待审核，**尚未完成本轮助手预审**。

| 批次 | 张数 | 本轮助手预审 | 用户最终审核 |
| --- | ---: | --- | --- |
| 1 | 1,000 | 已完成 | 全部待审核 |
'''
for i in range(2,10):README+=f'| {i} | {1000 if i<9 else 398:,} | 待处理 | 全部待审核 |\n'
README+='''
## 文件

- `batches/batch-001.txt` 至 `batch-009.txt`：固定完整批次名单。
- `batches/manifest.csv`：每张图片的批次和顺序。
- `batch-001/REPORT.md`：第一批预审结果。
- `before/metadata.csv`：全量重置前备份；`before/inventory.json` 记录原始图片、label 的 SHA256、尺寸、坐标和 metadata。
- `applied/`：第一批写入前 metadata 和 1,000 个 label 的原样备份、建议、逐文件结果。
- `verification.json`：全库一致性核对结果；`validation.json`：结构校验明细。

**不要直接用旧备份覆盖现有 metadata.csv**：会丢失之后的人工复查。写回工具有全字段及文件哈希保护；本批次写入时没有冲突或失败。
'''
(W/'README.md').write_text(README)
report=f'''# 第 1 批助手预审结果

本批 **1,000 张图片、原 765 个候选框**已逐图检查全景和所有现有框的局部。全景采用 672×376 原生像素，每页 6 张；候选框以原生裁剪和最近邻放大查看，必要处另看坐标网格。四个 250 张分组均有逐图建议及实际查看记录。结果只代表助手预审，**1,000 张的球框及四类分类仍全部待用户复查**。

- 改动 **14 个 label 文件**：删除 3 个鞋面/鞋带误框，另 11 个文件调整边界。候选框从 765 个变为 762 个；未凭相邻帧或另一只眼补造不可见的足球。
- 调整 **269 张图片**的场景标记，保留 Small、Occluded、Blurred、No Ball 多标签结构。
- **252 张存在疑点**，优先复查；其中 55 张需要手工核对或补画框，16 张需要辨认球是否可见。这两项是 252 张的子集，其余多为遮挡、运动模糊或 Small 临界。
- 预审认为较明确的 748 张也未自动通过，仍由用户确认。
- 写入跳过 0 张，失败 0 张。全库图片、批次外 label、划分、来源、原有备注及 dataset.yaml 均保留。结构校验 0 个错误。

## 主要问题

1. `frame_001650_left/right.png` 的第二个框是灰鞋；保留真实足球框，删除鞋框。
2. `frame_004995_right.png` 原框是鞋面/鞋带，删除。该图只作为候选无球，仍待用户确认。
3. 器械横杆旁球的旧框切球；在能辨清可见边界的视角扩大，其他视角保留疑点。
4. `frame_003599_left.png`、`frame_003661_left/right.png` 的近处手持球框带入手/背景，收紧到可见球体；不按理想圆形填补被手遮住的区域。
5. `frame_004504_left.png`、`frame_004618_left.png` 框含过量背景或地面阴影；`frame_004660_left/right.png` 框向右偏切掉左侧球缘，已调整。
6. 背景椅脚、伸手下方、柜边有漏标球；严重软边或遮挡使边界不能可靠确定时保留空文件并注明需补框，不标成确定无球。已有框之外的可疑残片也写入备注。

## 复查入口

```bash
/home/misaka/workspace/script/review_football_batch.sh 1
# 本批疑点优先（252 张），保存仍写原数据集：
/home/misaka/workspace/script/review_football_batch.sh 1 --priority
```

审核工具中会显示当前 label 框、四类标记和备注；需要补画/修框的请按备注处理后再通过。全部待审标志由用户手动操作解除。

## 清单及证据

- [所有 1,000 张逐图预审清单](prechecked.csv)
- [252 张疑点清单](priority-review.csv)
- [14 个 label 修改文件及原因](label-changes.csv)
- [55 张需手工核框/补框](manual-box-review.csv)
- [16 张可见性疑点](visibility-review.csv)
- [逐图完整建议和证据路径](proposals.json)
- `correction-preview/page-00.png` 至 `page-03.png`：红色旧框、绿色修改候选，全部已查看；空绿色侧表示删除误框。
- 备份与结果：`{result['audit']}`。

## 分类口径

Small 按完整球的尺度判断，本批 672 像素长边下约 40 像素为临界，裁边大球不按残片宽度标小球；Occluded 需要手、鞋、器械等前景实际盖住球，单纯接触或画面裁切不算；Blurred 看真实方向性拖影，低分辨率本身不等于运动模糊；No Ball 只表示本图未见足球，当前全部仍是待用户确认的候选结论。

本批只是第 1/9 批；其余 7,398 张尚未完成本轮助手预审。
'''
(B/'REPORT.md').write_text(report)
print(json.dumps({k:v for k,v in verify.items() if k not in ['coverage']},ensure_ascii=False))
