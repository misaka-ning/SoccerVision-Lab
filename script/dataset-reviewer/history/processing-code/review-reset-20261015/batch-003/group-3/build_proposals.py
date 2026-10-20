import json
from pathlib import Path
from collections import Counter
P=Path(__file__).parent
inv=json.loads((P/'inventory.json').read_text());m=json.loads((P/'manifest.json').read_text());notes=json.loads((P/'notes.json').read_text())
assert set(notes['opened_full'])==set(range(125));assert set(notes['opened_roi'])==set(range(25))
obs={}
for o in notes['observations']:
 for n in o['locals']: obs[n]=o
assert set(obs)==set(range(250))
props=[]
for n,x in enumerate(inv):
 o=obs[n];rs=[r for r in m['roi'] if r['local']==n];f=next(v['path'] for v in m['full'] if n in v['locals'])
 assert all(int(Path(r['page']).stem.split('-')[1]) in notes['opened_roi'] for r in rs)
 a={'filename':x['filename'],'index':x['index'],'scene_seen':True,'roi_boxes_seen':[r['box_index'] for r in rs],'action':o['action'],'flags':dict(zip(['Small','Occluded','Blurred','No Ball'],o['flags'])),'scene_certain':o['scene_certain'],'confidence':'high' if o['scene_certain'] and o['action']=='keep' else 'uncertain','reason':o['reason'],'evidence':list(dict.fromkeys([f]+[r['page'] for r in rs])),'expected_label_sha256':x['label_sha256'],'expected_image_sha256':x['image_sha256']}
 assert sorted(a['roi_boxes_seen'])==list(range(len(x['boxes'])))
 if n==89:
  a['action']='needs_visibility_review';a['reason']='机器人右臂内侧缝隙有白黑球状残片，但与后方鞋/结构及拖影混合，当前单帧足球身份和边界需人工确认；保留原候选与No Ball=0。'
 if n in [182,183]:
  box=x['boxes'][0]['xyxy'].copy();box[1]=179 if n==182 else 178
  a.update(action='replace',boxes_xyxy=[box],confidence='high',scene_certain=True,reason='鞋底明确遮挡球顶；原框上沿切掉右上仍可见的白色球面，已在原生坐标网格和新旧叠框中确认，将上沿分别扩至y=179/178，左右及下沿保持现有贴合边界，不补隐藏球面。')
  a['evidence']+=[str(P/'details-182-183.png'),str(P/'details-182-183-proposed.png')]
 props.append(a)
(P/'proposals.json').write_text(json.dumps(props,ensure_ascii=False,indent=2)+'\n')
s={'images':len(props),'existing_boxes':sum(len(x['boxes']) for x in inv),'opened_full':[v['path'] for v in m['full']],'opened_roi':list(dict.fromkeys(v['page'] for v in m['roi'])),'opened_detail':[str(P/'details-182-183.png'),str(P/'details-182-183-proposed.png')],'actions':dict(Counter(x['action'] for x in props)),'confidence':dict(Counter(x['confidence'] for x in props)),'pending_user_review':len(props),'scene_flag_changed_images':sum(any(x['flags'][k]!=inv[n]['meta'][k] for k in x['flags']) for n,x in enumerate(props)),'coverage':{'native_images_seen':250,'existing_roi_boxes_seen':sum(len(a['roi_boxes_seen']) for a in props),'full_pages_seen':125,'roi_pages_seen':25}}
(P/'summary.json').write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in s.items() if k not in ['opened_full','opened_roi','opened_detail']},ensure_ascii=False,indent=2))
