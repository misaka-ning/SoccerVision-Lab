import json,sys,math
from pathlib import Path
from collections import Counter
b=Path(__file__).parent.parent/f'group-{int(sys.argv[1])}'
prefix='' if int(sys.argv[1])==1 else 'head-';limit=250 if not prefix else 126
inv=json.load(open(b/'inventory.json'))[:limit];m=json.load(open(b/'manifest.json'));n=json.load(open(b/(prefix+'notes.json')))
pro=[]
for i,r in enumerate(inv):
 o={**n['observations'][str(i//2)],**n.get('per_image_overrides',{}).get(str(i),{})};flags=dict(zip(['Small','Occluded','Blurred','No Ball'],o['flags']));roi=[x for x in m['roi'] if x['local']==i];e=[str(b/'full'/f'page-{i//2:03d}.png')]+sorted(set(x['page'] for x in roi))
 if int(sys.argv[1])==1 and i in (124,125):e.append(str(b/f'detail-{i:03d}.png'))
 p={'filename':r['filename'],'index':r['index'],'scene_seen':True,'roi_boxes_seen':[x['box_index'] for x in roi],'action':o['action'],'flags':flags,'scene_certain':True,'confidence':'high','reason':o['reason'],'evidence':e,'expected_image_sha256':r['image_sha256'],'expected_label_sha256':r['label_sha256']}
 
 if o['action']=='replace':p['boxes_xyxy']=o['boxes_xyxy']
 p['evidence']+=o.get('evidence',[])
 p['scene_certain']=o.get('scene_certain',o['action'] not in ('needs_visibility_review','needs_manual_bbox_annotation'))
 p['confidence']=o.get('confidence','high' if p['scene_certain'] else 'uncertain')
 pro.append(p)
(b/(prefix+'proposals.json')).write_text(json.dumps(pro,ensure_ascii=False,indent=2))
full=[x['path'] for x in m['full'] if min(x['locals'])<limit];roi=sorted(set(x['page']for x in m['roi'] if x['local']<limit))
assert set(full)==set(n['actual_opened_full_pages']);assert set(roi)<=set(n['actual_opened_roi_pages'])
for i,p in enumerate(pro):
 assert p['filename']==inv[i]['filename'];assert p['scene_seen'];assert set(p['roi_boxes_seen'])==set(x['box_index']for x in inv[i]['boxes']);assert all(Path(e).exists()for e in p['evidence'])
 c=len(p.get('boxes_xyxy',[])) if p['action']=='replace' else len(inv[i]['boxes']);assert p['flags']['No Ball']==str(int(c==0))
 for box in p.get('boxes_xyxy',[]):assert all(math.isfinite(v) for v in box)and 0<=box[0]<box[2]<=inv[i]['width']and 0<=box[1]<box[3]<=inv[i]['height']
s={'images':limit,'actions':dict(Counter(p['action']for p in pro)),'flags':{k:sum(p['flags'][k]=='1'for p in pro)for k in ['Small','Occluded','Blurred','No Ball']},'actual_opened_full_pages':n['actual_opened_full_pages'],'actual_opened_roi_pages':n['actual_opened_roi_pages'],'labels_written_to_dataset':0,'approval_flags_cleared':0,'validation':{'coverage':True,'schema':True,'evidence_paths_exist':True,'geometry_finite_legal':True,'final_box_count_matches_no_ball':True},'review_status':'球框和场景分类均待用户复查；未批准。'}
(b/(prefix+'summary.json')).write_text(json.dumps(s,ensure_ascii=False,indent=2));print({k:v for k,v in s.items()if k not in ['actual_opened_full_pages','actual_opened_roi_pages']})
