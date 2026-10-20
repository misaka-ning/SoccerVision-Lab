#!/usr/bin/env python3
"""Consolidate persisted, visually observed decisions. Never infer approvals."""
import json
from pathlib import Path
from collections import Counter
W=Path(__file__).resolve().parent
B=W/'batch-001';COLS=['Small','Occluded','Blurred','No Ball']
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def base(r):
 return dict(filename=r['filename'],index=r['index'],scene_seen=True,roi_boxes_seen=[q['box_index'] for q in r['boxes']],action='keep',scene_certain=True,confidence='high',expected_label_sha256=r['label_sha256'],expected_image_sha256=r['image_sha256'])
allp=[]
for group in range(1,5):
 p=B/f'group-{group}'; inv=json.loads((p/'inventory.json').read_text());manifest=json.loads((p/'manifest.json').read_text());decisions={}
 if group==1:
  n=json.loads((p/'notes.json').read_text());decisions={int(k):v for k,v in n['decisions'].items()};full=set(n['opened_full']+n['root_opened_full']);roi=set(n['opened_roi']+n['root_opened_roi'])
 elif group==2:
  props=json.loads((p/'proposals.json').read_text());assert len(props)==250;allp+=props;continue
 elif group==3:
  n=json.loads((p/'review-notes.json').read_text())
  for o in n['observations']:
   for i in o['locals']:
    d=decisions.setdefault(i,{});v={k:z for k,z in o.items() if k not in ['locals','evidence']};v['flags']=dict(zip(COLS,o['flags']));d.update(v)
  full={str(p.resolve()/'full'/f'page-{i:02d}.png') for i in n['opened_full']+n['root_opened_full']};roi={str(p.resolve()/'roi'/f'page-{i:02d}.png') for i in n['opened_roi']+n['root_opened_roi']}
  # Native ROI review reveals a shifted box; retain it for human repair.
  for i in [232,233,236]:decisions[i].update(action='needs_manual_bbox_annotation',scene_certain=False,reason='放大ROI中球在框左侧/下侧，旧框疑切球缘且边界软化；现候选保留，请用户手工贴球边，勿按鞋的边缘扩框。')
 else:
  n=json.loads((p/'root-notes.json').read_text());full={str(p.resolve()/'full'/f'page-{i:02d}.png') for i in n['viewed_full']};roi={str(p.resolve()/'roi'/f'page-{i:02d}.png') for i in n['viewed_roi']}
  for i in range(250):
   neg=i in list(range(84,86))+list(range(106,110))+list(range(118,120))+list(range(128,132))+list(range(134,138))+[142,143,158,159,244,245,246,247]
   flags=dict(zip(COLS,'0001' if neg else ('1000' if i<190 else '0000')))
   reason='逐张原生全景及现框局部可见唯一足球；鞋临近、接触或位于球后不直接视为遮挡。球体矩形四角背景正常，保留合理候选，待用户复查。'
   if neg:reason='逐张原生全景及画面四边未见可见足球，画面为门、地面、家具及鞋；候选无球保留空label，待用户最终确认。'
   decisions[i]=dict(flags=flags,reason=reason,action='keep',scene_certain=True)
  blur=list(range(22,28))+[36,37,52,53,56,57]+list(range(58,64))+[70,71]+list(range(78,84))+[86,87]+list(range(96,106))+list(range(114,118))+[126,127,140,141,148,149,154,155,156,157,162,163,166,167,168,169,170,171,174,175,182,183,184,185,190,191,198,199,204,205,208,209,230,231,234,235,242,243,246,247,248,249]
  for i in blur:decisions[i]['flags']['Blurred']='1';decisions[i]['reason']+=' 球或全景可见方向性拖影，Blurred=1。'
  for i in [102,103,104,105,176,177,178,179,194,195]:decisions[i]['flags']['Occluded']='1';decisions[i]['reason']+=' 鞋底作为前景实际盖住球上缘，Occluded=1。'
  for i in [14,15,40,41,42,43,44,45,46,47,48,49,64,65,68,69,74,75,114,115,116,117,152,153,164,165,184,185,210,211,212,213]:decisions[i]['scene_certain']=False;decisions[i]['reason']+=' 鞋与球接触处前后关系/软边仍需用户核对，未贸然计为遮挡。'
  for i in [26,27,170,171,182,183,186,187,188,189]+list(range(210,230)):
   decisions[i]['scene_certain']=False;decisions[i]['reason']+=' 完整尺度接近40px，Small为暂定，需复核。'
  for i in [2,3,60,61,66,67,74,75,76,77,78,79,90,94,95,151,162,163,166,167,242,243]:
   decisions[i].update(action='needs_manual_bbox_annotation',scene_certain=False);decisions[i]['reason']+=' 旧框有偏移/鞋或阴影留白疑点，局部软边不能可靠自动贴边；保留旧候选，用户需手工核对。'
  for i,box in {122:[504,152,525,175],150:[516,151,545,176],160:[490,157,517,181],161:[480,157,507,180]}.items():
   decisions[i].update(action='replace',boxes_xyxy=[box],reason='已查看原生5倍坐标网格：'+('原框上下/右侧包含较大背景及地面阴影，按可见球体收紧。' if i in [122,150] else '原框向右偏，左侧可见球缘在框外；扩展左边并贴合球体其余边界。')+' 修正仅为助手候选，仍待用户复核。')
  decisions[245].update(action='replace',boxes_xyxy=[],reason='原生全景、ROI及5倍坐标网格均确认现框实际是鞋面/鞋带，不是足球；删除这一个误框。全景未见其他球，候选无球仍待用户确认。')
 assert set(decisions)==set(range(250)),(group,sorted(set(range(250))-decisions.keys()))
 props=[]
 for i,r in enumerate(inv):
  q=base(r);q.update(decisions[i]);q['confidence']='high' if q.get('scene_certain',True) and q['action'] in ['keep','replace'] else 'uncertain'
  fe=next(f['path'] for f in manifest['full'] if i in f['locals']);ev=[fe];ev+=sorted({z['page'] if isinstance(z['page'],str) else str(p.resolve()/'roi'/f"page-{z['page']:02d}.png") for z in manifest['roi'] if z['local']==i})
  # ROI page indices in manifest map to the exact native-pixel sheet.
  q['evidence']=ev
  if group==4 and i in [122,150,160,161,245]:q['evidence']+=[str(p.resolve()/f'detail-grid-{0 if i in [66,67,74,75] else 1 if i in [122,150,151,160] else 2}.png')]
  assert fe in full
  for e in ev[1:]:assert e in roi or Path(e).name.startswith('detail-grid-'),(group,i,e)
  props.append(q)
 save(p/'proposals.json',props);save(p/'summary.json',dict(images=250,existing_boxes=sum(len(x['boxes']) for x in inv),opened_full=sorted(full),opened_roi=sorted(roi),actions=dict(Counter(q['action'] for q in props)),pending_user_review=250));allp+=props
assert len(allp)==1000 and len({q['filename'] for q in allp})==1000
save(B/'proposals.json',allp)
print(json.dumps(dict(images=len(allp),actions=dict(Counter(q['action'] for q in allp)),confidence=dict(Counter(q['confidence'] for q in allp))),ensure_ascii=False))
