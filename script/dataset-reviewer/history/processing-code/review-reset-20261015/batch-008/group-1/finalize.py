from pathlib import Path
import json,hashlib,math
from collections import Counter
W=Path(__file__).resolve().parent
inv=json.loads((W/'inventory.json').read_text());m=json.loads((W/'manifest.json').read_text());n=json.loads((W/'notes.json').read_text());FLAGS=('Small','Occluded','Blurred','No Ball')
assert len(inv)==250 and set(n['observations'])==set(map(str,range(250)))
assert not any(o.get('root_review_pending') for o in n['observations'].values()),'Root second pass still pending'
full={i:p['path'] for p in m['full'] for i in p['locals']}
roi={i:{} for i in range(250)}
for r in m['roi']:roi[r['local']][r['box_index']]=r['page']
assert len(n['actual_opened_full_pages'])==125 and set(n['actual_opened_full_pages'])==set(full.values())
assert len(n['actual_opened_roi_pages'])==len(set(n['actual_opened_roi_pages']))==len(set(r['page'] for r in m['roi'])) and set(n['actual_opened_roi_pages'])==set(r['page'] for r in m['roi'])
props=[]
for local,b in enumerate(inv):
 o=n['observations'][str(local)];oldindices=[box['box_index'] for box in b['boxes']]
 assert sorted(roi[local])==oldindices
 p={'filename':b['filename'],'index':b['index'],'scene_seen':True,'roi_boxes_seen':oldindices,'action':o.get('action','keep'),'flags':o['flags'],'scene_certain':o.get('scene_certain',True),'confidence':o.get('confidence','high'),'reason':o['reason'],'evidence':list(dict.fromkeys([full[local],*roi[local].values(),*[str(W/x) for x in o.get('evidence_extra',[])]])),'expected_image_sha256':b['image_sha256'],'expected_label_sha256':b['label_sha256'],'label_review_required':'1','scene_review_required':'1','user_approved':False}
 if p['action']=='replace':p['boxes_xyxy']=o['boxes_xyxy']
 finalboxes=p['boxes_xyxy'] if p['action']=='replace' else [box['xyxy'] for box in b['boxes']]
 assert p['flags']['No Ball']==('0' if finalboxes else '1')
 for x1,y1,x2,y2 in finalboxes:assert 0<=x1<x2<=b['width'] and -1e-6<=y1<y2<=b['height']+1e-6
 for key in ('image','label'):assert hashlib.sha256(Path(b[key+'_path']).read_bytes()).hexdigest()==b[key+'_sha256']
 for path in p['evidence']:assert Path(path).is_absolute() and Path(path).is_file()
 props.append(p)
summary={'group':1,'images':250,'boxes_before':sum(len(b['boxes']) for b in inv),'boxes_after':sum(len(p['boxes_xyxy']) if p['action']=='replace' else len(b['boxes']) for b,p in zip(inv,props)),'actions':dict(Counter(p['action'] for p in props)),'flags':{f:sum(p['flags'][f]=='1' for p in props) for f in FLAGS},'scene_flag_changes':sum(any(p['flags'][f]!=b['meta'][f] for f in FLAGS) for b,p in zip(inv,props)),'replacement_locals':[i for i,p in enumerate(props) if p['action']=='replace'],'uncertain_locals':[i for i,p in enumerate(props) if p['confidence']=='uncertain'],'actual_opened_full_pages':n['actual_opened_full_pages'],'actual_opened_roi_pages':n['actual_opened_roi_pages'],'pending_only':True,'all_require_user_review':True,'labels_written_to_dataset':0,'approval_flags_cleared':0,'user_approved':0,'canonical_dataset_written':False,'validation':{'coverage':True,'evidence':True,'source_hashes':True,'No_Ball_consistency':True,'geometry':True},'review_note':'250张均逐幅查看原生全图，并查看全部200个旧框ROI；所有候选与四项场景标记继续双待审，未自动通过用户审核。'}
for path,value in [('proposals.json',props),('summary.json',summary)]:
 data=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8');(W/path).write_bytes(data);print(path,hashlib.sha256(data).hexdigest())
print(json.dumps({k:summary[k] for k in ('images','boxes_before','boxes_after','actions','flags','scene_flag_changes','replacement_locals','uncertain_locals')},ensure_ascii=False))
