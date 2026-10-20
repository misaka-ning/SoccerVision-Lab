import json
from pathlib import Path
P=Path(__file__).resolve().parent
def load():
 return json.loads((P/'notes.json').read_text()) if (P/'notes.json').exists() else {'opened_full':[],'opened_roi':[],'decisions':{}}
def record(full,roi,spans):
 n=load()
 for pages,key,folder in [(full,'opened_full','full'),(roi,'opened_roi','roi')]:
  for i in pages:
   path=str(P/folder/f'page-{i:03d}.png')
   if path not in n[key]:n[key].append(path)
 for start,end,flags,reason,*extra in spans:
  action=extra[0]if extra else'keep';certain=extra[1]if len(extra)>1 else True
  for i in range(start,end+1):n['decisions'][str(i)]={'flags':dict(zip(['Small','Occluded','Blurred','No Ball'],map(str,flags))),'reason':reason,'action':action,'scene_certain':certain}
 (P/'notes.json').write_text(json.dumps(n,ensure_ascii=False,indent=2)+'\n')
def finish():
 n=load();rs=json.loads((P/'inventory.json').read_text());m=json.loads((P/'manifest.json').read_text());out=[]
 for i,r in enumerate(rs):
  assert str(i)in n['decisions'],i
  full=[q['path']for q in m['full']if i in q['locals']];roi=[q for q in m['roi']if q['local']==i]
  assert all(p in n['opened_full']for p in full)
  assert all(q['page']in n['opened_roi']for q in roi)
  d=n['decisions'][str(i)]
  q={'filename':r['filename'],'index':r['index'],'scene_seen':True,'roi_boxes_seen':[b['box_index']for b in roi],
     'expected_label_sha256':r['label_sha256'],'expected_image_sha256':r['image_sha256'],
     'evidence':list(dict.fromkeys(full+[b['page']for b in roi])),**d}
  q['evidence']+=q.pop('extra_evidence',[])
  q['confidence']='high'if d['scene_certain']and d['action']in['keep','replace']else'uncertain';out.append(q)
 (P/'proposals.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
 from collections import Counter
 summary={'images':len(out),'existing_boxes':len(m['roi']),'opened_full':n['opened_full'],'opened_roi':n['opened_roi'],'actions':dict(Counter(q['action']for q in out)),'pending_user_review':len(out)}
 summary['opened_detail']=n.get('opened_detail',[])
 (P/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 return summary
