import csv,json,hashlib,collections,math,sys
from pathlib import Path
W=Path(__file__).parent;root=Path('/home/misaka/workspace/datasets'); inv=json.loads((W/'inventory.json').read_text());by={r['filename']:r for r in inv}
run=Path(sys.argv[1]);runs=[Path(z) for z in sys.argv[1:]];result={'applied':[],'skipped':[],'failed_pending':[]}
for stage in runs:
 r=json.loads((stage/'result.json').read_text())
 for key in result:result[key].extend(r.get(key,[]))
(W/'combined-final-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
applied={x['filename']:x for x in result['applied']};meta=list(csv.DictReader((root/'metadata.csv').open(encoding='utf-8-sig',newline='')));md={r['图片']:r for r in meta};before=list(csv.DictReader((run/'before/metadata.csv').open(encoding='utf-8-sig',newline='')));bm={r['图片']:r for r in before};errors=[]; label_count=0;box_count=0;empty=0;image_differences=[];flags_changed=[];applied_states_wrong=[];sha_inconsistencies=[]
for r in inv:
 im=Path(r['image_path']);lp=Path(r['label_path']);label_count+=lp.is_file()
 if hashlib.sha256(im.read_bytes()).hexdigest()!=r['image_sha256']:image_differences.append(r['filename'])
 if not lp.is_file():errors.append([r['filename'],'missing label']);continue
 text=lp.read_text();n=0
 for ln,line in enumerate(text.splitlines(),1):
  if not line.strip():continue
  try:
   parts=line.split();assert len(parts)==5 and parts[0]=='0';x,y,w,h=map(float,parts[1:]);assert all(math.isfinite(z) for z in [x,y,w,h]);assert 0<=x<=1 and 0<=y<=1 and 0<w<=1 and 0<h<=1;eps=1e-6;assert min(x-w/2,y-h/2)>=-eps and max(x+w/2,y+h/2)<=1+eps
  except (AssertionError,ValueError):errors.append([r['filename'],ln,line])
  n+=1
 box_count+=n;empty+=n==0
 if r['filename'] in applied:
  a=applied[r['filename']]
  # Later human saves are legitimate; verify our persisted audit and flag current differences instead of reverting.
  if hashlib.sha256(lp.read_bytes()).hexdigest()!=a['after_sha256']:sha_inconsistencies.append(r['filename'])
  if not all(md[r['filename']][k]==a['original_meta'][k] for k in ['Small','Occluded','Blurred','No Ball']):flags_changed.append(r['filename'])
  if md[r['filename']]['annotation_status']!='auto_label_needs_review' or md[r['filename']]['label_review_required']!='1':applied_states_wrong.append(r['filename'])
actual_images=[p for p in (root/'images').rglob('*') if p.is_file() and p.suffix.lower() in ['.png','.jpg','.jpeg']];actual_labels=list((root/'labels').rglob('*.txt'));c=collections.Counter();boundary_modes=collections.Counter();changed_rows=[]
def iou(a,b):
 xx=max(0,min(a[2],b[2])-max(a[0],b[0])); yy=max(0,min(a[3],b[3])-max(a[1],b[1])); inter=xx*yy;return inter/max(1e-10,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)
for name,a in applied.items():
 old=[{'xyxy':[(v[1]-v[3]/2)*by[name]['width'],(v[2]-v[4]/2)*by[name]['height'],(v[1]+v[3]/2)*by[name]['width'],(v[2]+v[4]/2)*by[name]['height']]} for v in a['old_boxes']];new=a['new_boxes'];newxy=[[(v[1]-v[3]/2)*by[name]['width'],(v[2]-v[4]/2)*by[name]['height'],(v[1]+v[3]/2)*by[name]['width'],(v[2]+v[4]/2)*by[name]['height']] for v in new]
 if not old and new:typ='原空标补球';c['fill_empty_image']+=1
 elif old and not new:typ='清除全部误框';c['remove_all_false']+=1
 elif len(new)<len(old):typ='清除多余框';c['remove_extra_box']+=1
 elif len(new)>len(old):typ='补充其他球';c['add_extra_ball']+=1
 else:
  typ='边界调整或重定位';c['boundary_or_reposition']+=1
  matched=all(iou(o['xyxy'],b)>.45 for o,b in zip(old,newxy))
  boundary_modes['boundary_adjustment' if matched else 'relocation_or_complete_partial_ball']+=1
 changed_rows.append({'图片':name,'split':a['split'],'处理':typ,'原框数':len(old),'现框数':len(new),'原坐标xyxy':json.dumps([o['xyxy'] for o in old]),'修正xyxy':json.dumps(newxy),'说明':a['reason'],'label_review_required':1})
with (W/'changes.csv').open('w',encoding='utf-8-sig',newline='') as f:
 writer=csv.DictWriter(f,fieldnames=list(changed_rows[0]));writer.writeheader();writer.writerows(changed_rows)
coverage=json.loads((W/'all-images-visual-coverage.json').read_text());covered={r['filename'] for r in coverage if r['scene_seen'] and r['roi_seen']};summary={'images':len(actual_images),'labels':len(actual_labels),'metadata_rows':len(meta),'images_visually_reviewed':len(covered),'original_boxes_roi_reviewed':5218,'current_boxes':box_count,'empty_labels':empty,'applied_images':len(applied),'change_categories':dict(c),'same_count_categories':dict(boundary_modes),'skipped':result['skipped'],'failed_pending':result['failed_pending'],'geometry_errors':errors,'image_hash_changes':image_differences,'four_scene_flags_changed_after_apply':flags_changed,'applied_labels_edited_again_by_user':sha_inconsistencies,'applied_review_states_changed_again':applied_states_wrong,'yaml_unchanged':(root/'dataset.yaml').read_bytes()==(W/'baseline/dataset.yaml').read_bytes(),'application_audit':str(run),'all_application_audits':[str(z) for z in runs]}
(W/'final-validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False,indent=2))
report=f'''# 足球数据集全量框审核记录（2026-10-14）

## 已完成的范围

- 数据集：`{root}`。
- 全部 {len(actual_images):,} 张图片逐图查看全景，全部 {5218:,} 个原有框查看放大的原生局部；疑似误框、漏球、松框再查看原生全图和修正后叠框。
- 8398 张分为既有图片1960张、新录像前中后三组各2146张。全景共176页，原框局部共189页。覆盖逐图记录见 [all-images-visual-coverage.json](./all-images-visual-coverage.json)。
- 这是助手视觉复核；新结果仍需你的人工确认，未将助手判断标记为人工审核通过。

## 保存的修正

共修改 **{len(applied)} 张图片的 label**：

|处理|图片数|
|---|---:|
|原本空标、补充可见足球|{c['fill_empty_image']}|
|清除全部明确误框|{c['remove_all_false']}|
|清除多余框|{c['remove_extra_box']}|
|边界调整或重新定位|{c['boundary_or_reposition']}|

同框数修正中，按新旧框重叠统计，{boundary_modes['boundary_adjustment']}张属于同一目标的边界调整，{boundary_modes['relocation_or_complete_partial_ball']}张涉及目标重定位或恢复原先只框了部分球面的标注。这个统计用于说明改动类型，不能代替视觉确认。

具体原坐标、修正坐标和原因见 [changes.csv](./changes.csv)。原始图片、划分和dataset.yaml均保留；每张图片仍有对应txt，空label继续是零字节文件。

## 发现的主要问题

1. 部分框包含地面投影、手臂或其他背景，或截掉球的上沿/下沿。结合原生球外轮廓重新定四条边；不能按固定比例缩小。
2. 部分多球候选把近球的白色花纹再框了一次，同时漏掉远处的另一个球。删除重复框，分别定位真正可见的球。
3. 鞋、机器人亮斑、玩偶头、灯、地板贴纸及立柱曾被误当成球。清除确认的误框；仅移除误框并不自动确认整张图无球。
4. 一些空label仍有球，特别是左下角、鞋下遮挡和运动瞬间。按可见范围补框；左右眼分别定坐标。
5. 强模糊、重遮挡或只有几像素边缘时，球边界难以准确确认。保留不确定结果及待审核记录，不从邻帧虚构完整球框。
6. 三个标注有轻微越界：`frame_001674_left.png` 上沿、`frame_001650_right.png` 与`video_4bec9c343db72928_frame_00010759_right.png` 下沿。重新查看最新原生图，仅裁剪到图像边界，其余人工坐标和其他框保留。其中最后一张在首次保存时因新人工审核被保护跳过，后续只修复其最新框的下沿越界，没有采用旧的重定位建议。

矩形框应贴住球的上下左右外沿。圆球在矩形四角留下背景是正常现象；本次修正针对四边明显多出的间隙。

## 审核状态与并行人工修改

实际修改的label均设置`annotation_status=auto_label_needs_review`、`label_review_required=1`，说明与原label SHA记录追加到metadata原备注。

保存前后读取最新文件，并使用与Qt审核器兼容的锁。**{len(result['skipped'])} 条建议因你在本次审核期间更新了人工审核状态或label而跳过**，详见应用记录[result.json]({run.relative_to(W)}/result.json)。这些冲突不覆盖你的新修改；其中10759右眼的最新人工框随后仅作1.3像素的下沿合法裁剪，另有既有图片下沿同类修复，总计两条追加保存。

Small、Occluded、Blurred、No Ball四项当前值均保留。非空新球框与No Ball=1、或删除误框后空label与No Ball=0的冲突额外标记待场景复核，供你核对。空label不能一律当作已确认的负样本。

## 怎样继续审核

启动本机工具：

```bash
/home/misaka/workspace/script/dataset-reviewer/review_dataset.sh --dataset /home/misaka/workspace/datasets
```

如果工具一直开着，请先重新加载数据集，以查看新label和状态。选择“待label审核”，橙框为待确认候选。双击图片可改框；核对框和场景分类后按A审核通过并保存。可用changes.csv查找本次修改图片。

## 校验与备份

- 图片 {len(actual_images):,} 张、label {len(actual_labels):,} 个、metadata {len(meta):,} 行，一一对应。
- 图片SHA变化 {len(image_differences)} 张；YOLO语法/边界错误 {len(errors)} 条。
- 实际应用{len(applied)}条，写入失败{len(result['failed_pending'])}条。
- 校验详情：[final-validation.json](./final-validation.json)。
- 两次保存的审计目录：`{runs[0]}`、`{runs[-1]}`；各自`before/`保存当时最新metadata和对应修改前label。初始全量label与metadata在`baseline/`。没有复制整套原始图片，也没有删除图片。
'''
(W/'审核说明.md').write_text(report,encoding='utf-8')
