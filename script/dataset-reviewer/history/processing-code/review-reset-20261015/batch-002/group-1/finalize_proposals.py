import json
from pathlib import Path
import note_review as n
p=Path(__file__).parent
n.notes['details']=[str(p/f'detail-n{i}.png') for i in [249,18,16]]+[str(p/'detail-n18-before-after.png')]
n.notes['observations']['18'].update(action='keep',certain=False,reason='箱体下蓝白足球上缘被箱体遮挡；原生网格及前后对比显示旧框基本贴合，左右边界仅数像素软化并混入箱体阴影。曾试扩到375但增加无效空隙，已否决该方案并保留原label；请人工重点核对左右软边，不能把阴影当球体。')
n.notes['observations']['18'].pop('boxes_xyxy',None)
for i in [6,7]:n.notes['observations'][str(i)]['flags'][0]='0'
n.save()
assert sorted(n.notes['full_pages'])==list(range(125))
assert sorted(n.notes['roi_pages'])==list(range(15))
assert len(n.notes['observations'])==250
out=[]
for k,a in enumerate(n.inv):
 d=n.notes['observations'][str(k)]
 full=[r['path'] for r in n.m['full'] if k in r['locals']]
 roi=[r for r in n.m['roi'] if r['local']==k]
 # Parent renderer's manifest carries a full absolute page path.
 ev=list(full)
 for r in roi:
  rp=r.get('path') or r.get('page_path') or r.get('page')
  if isinstance(rp,int):rp=str(p/'roi'/f'page-{rp:03d}.png')
  elif isinstance(rp,str) and not rp.startswith('/'):rp=str(p/'roi'/rp)
  if rp and rp not in ev:ev.append(rp)
 if k in [249,18,16]:ev.append(str(p/f'detail-n{k}.png'))
 if k==18:ev.append(str(p/'detail-n18-before-after.png'))
 if '蓝色折叠凳' in d['reason']:
  for page in [52,59]:
   e=str(p/'full'/f'page-{page:03d}.png')
   if e not in ev:ev.append(e)
 action=d.get('action','keep')
 boxes=d.get('boxes_xyxy') if action=='replace' else None
 record={'filename':a['filename'],'index':a['index'],'scene_seen':True,'roi_boxes_seen':[r['box_index'] for r in roi],'action':action,'flags':dict(zip(['Small','Occluded','Blurred','No Ball'],d['flags'])),'scene_certain':d['certain'],'confidence':'high' if d['certain'] else 'uncertain','reason':d['reason'],'evidence':ev,'expected_label_sha256':a['label_sha256'],'expected_image_sha256':a['image_sha256']}
 if boxes is not None:record['boxes_xyxy']=boxes
 out.append(record)
assert all(Path(e).is_file() for r in out for e in r['evidence'])
assert all(sorted(r['roi_boxes_seen'])==[b['box_index'] for b in a['boxes']] for r,a in zip(out,n.inv))
(p/'proposals.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
summary={'images_reviewed':250,'existing_boxes_reviewed':sum(len(a['boxes']) for a in n.inv),'actual_opened_full_pages':[str(p/'full'/f'page-{i:03d}.png') for i in sorted(n.notes['full_pages'])],'actual_opened_roi_pages':[str(p/'roi'/f'page-{i:03d}.png') for i in sorted(n.notes['roi_pages'])],'actual_opened_details':n.notes['details'],'coverage_images':list(range(250)),'coverage_boxes':{r['filename']:r['roi_boxes_seen'] for r in out},'uncertain_images':sum(not r['scene_certain'] for r in out),'replace_files':[r['filename'] for r in out if r['action']=='replace'],'labels_written_to_dataset':0,'approval_flags_cleared':0}
(p/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print({k:v for k,v in summary.items() if k in ['images_reviewed','existing_boxes_reviewed','uncertain_images','replace_files']})
