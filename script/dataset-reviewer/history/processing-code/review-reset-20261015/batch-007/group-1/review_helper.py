import json,sys,math
from pathlib import Path
from collections import Counter
B=Path(__file__).parent.parent
FLAGS=['Small','Occluded','Blurred','No Ball']
def files(g):
 b=B/f'group-{g}';pre='' if g==1 else 'head-';return b,pre,b/(pre+'notes.json')
def load(g):
 b,pre,p=files(g);d=json.load(open(p)) if p.exists() else {'actual_opened_full_pages':[],'actual_opened_roi_pages':[],'observations':{},'overrides':{}};return b,pre,p,d
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
mode=sys.argv[1];g=int(sys.argv[2]);b,pre,p,d=load(g)
if mode=='record':
 a,z=int(sys.argv[3]),int(sys.argv[4]);f=sys.argv[5];reason=sys.argv[6];action=sys.argv[7] if len(sys.argv)>7 else 'keep'
 for n in range(a,z+1):
  full=str(b/'full'/f'page-{n:03d}.png')
  if full not in d['actual_opened_full_pages']:d['actual_opened_full_pages'].append(full)
  d['observations'][str(n)]={'flags':f,'reason':reason,'action':action}
 save(p,d)
elif mode=='roi':
 for n in map(int,sys.argv[3:]):
  roi=str(b/'roi'/f'page-{n:03d}.png')
  if roi not in d['actual_opened_roi_pages']:d['actual_opened_roi_pages'].append(roi)
 save(p,d)
elif mode=='final':
 limit=250 if g==1 else 126;inv=json.load(open(b/'inventory.json'))[:limit];m=json.load(open(b/'manifest.json'));pro=[]
 for i,r in enumerate(inv):
  o={**d['observations'][str(i//2)],**d['overrides'].get(str(i),{})};f=dict(zip(FLAGS,o['flags']));roi=[x for x in m['roi']if x['local']==i]
  q={'filename':r['filename'],'index':r['index'],'scene_seen':True,'roi_boxes_seen':[x['box_index']for x in r['boxes']],'action':o['action'],'flags':f,'scene_certain':o.get('scene_certain',o['action']=='keep' or o['action']=='replace'),'confidence':o.get('confidence','high' if o['action']in ('keep','replace')else 'uncertain'),'reason':o['reason'],'evidence':list(dict.fromkeys([str(b/'full'/f'page-{i//2:03d}.png')]+[x['page']for x in roi]+o.get('evidence',[]))),'expected_image_sha256':r['image_sha256'],'expected_label_sha256':r['label_sha256'],'label_review_required':'1','scene_review_required':'1','user_approved':False}
  if o['action']=='replace':q['boxes_xyxy']=o['boxes_xyxy']
  assert all(Path(x).is_file()for x in q['evidence'])
  bs=q['boxes_xyxy']if q['action']=='replace'else [x['xyxy']for x in r['boxes']]
  assert q['flags']['No Ball']==str(int(not bs)),(i,q)
  for v in bs:assert all(math.isfinite(x)for x in v)and -1e-6<=v[0]<v[2]<=r['width']+1e-6 and -1e-6<=v[1]<v[3]<=r['height']+1e-6,(i,v)
  pro.append(q)
 full=[x['path']for x in m['full']if min(x['locals'])<limit];roi=sorted(set(x['page']for x in m['roi']if x['local']<limit))
 assert set(full)==set(d['actual_opened_full_pages']);assert set(roi)==set(d['actual_opened_roi_pages'])
 s={'images':limit,'actions':dict(Counter(q['action']for q in pro)),'flags':{k:sum(q['flags'][k]=='1'for q in pro)for k in FLAGS},'actual_opened_full_pages':d['actual_opened_full_pages'],'actual_opened_roi_pages':d['actual_opened_roi_pages'],'labels_written_to_dataset':0,'approval_flags_cleared':0,'user_approved':0,'pending_only':True,'all_require_user_review':True,'canonical_dataset_written':False,'validation':{'coverage':True,'schema':True,'evidence_paths_exist':True,'geometry_finite_legal':True,'final_box_count_matches_no_ball':True},'review_status':'球框与场景分类均待用户复查，未批准。'}
 save(b/(pre+'proposals.json'),pro);save(b/(pre+'summary.json'),s);print({k:v for k,v in s.items()if not k.startswith('actual_')})
