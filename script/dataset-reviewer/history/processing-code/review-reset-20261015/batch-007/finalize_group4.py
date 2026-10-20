"""Assemble root's actual full/ROI observations; pending proposals only."""
from collections import Counter
import json
from pathlib import Path
W=Path(__file__).resolve().parent/'group-4'
inv=json.loads((W/'inventory.json').read_text()); m=json.loads((W/'manifest.json').read_text())
def save(p,o): p.write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n')
parts=[]; summaries=[]
for part,ns in [('head',range(126)),('tail',range(126,250))]:
 o=json.loads((W/f'{part}-notes.json').read_text()); assert set(map(int,o['decisions']))==set(ns)
 qs=[]
 for n in ns:
  b=inv[n];q=dict(o['decisions'][str(n)]);extra=q.pop('evidence_extra',[])
  q.update(filename=b['filename'],index=b['index'],scene_seen=True,roi_boxes_seen=[v['box_index'] for v in b['boxes']],expected_image_sha256=b['image_sha256'],expected_label_sha256=b['label_sha256'],evidence=[next(p['path'] for p in m['full'] if n in p['locals'])]+sorted({v['page'] for v in m['roi'] if v['local']==n})+extra)
  count=len(q['boxes_xyxy']) if q['action']=='replace' else len(b['boxes'])
  assert q['flags']['No Ball']==('0' if count else '1')
  assert set(q['evidence'][:1])<=set(o['actual_opened_full_pages'])
  assert {v['page'] for v in m['roi'] if v['local']==n}<=set(o['actual_opened_roi_pages'])
  assert all(Path(e).is_file() for e in q['evidence'])
  qs.append(q)
 s=dict(images=len(qs),local_range=[min(ns),max(ns)],actual_opened_full_pages=o['actual_opened_full_pages'],actual_opened_roi_pages=o['actual_opened_roi_pages'],actions=dict(Counter(q['action'] for q in qs)),flags={k:sum(q['flags'][k]=='1' for q in qs) for k in ['Small','Occluded','Blurred','No Ball']},pending_only=True,all_require_user_review=True,labels_written_to_dataset=0,approval_flags_cleared=0,user_approved=0,canonical_dataset_written=False,reviewer='root',frozen=True)
 save(W/f'{part}-proposals.json',qs);save(W/f'{part}-summary.json',s);parts+=qs;summaries.append(s)
full=sorted({p for s in summaries for p in s['actual_opened_full_pages']});roi=sorted({p for s in summaries for p in s['actual_opened_roi_pages']})
assert len(full)==125 and set(full)=={p['path'] for p in m['full']}
assert set(roi)=={v['page'] for v in m['roi']}
assert [q['index'] for q in parts]==list(range(750,1000))
s=dict(images=250,actual_opened_full_pages=full,actual_opened_roi_pages=roi,actions=dict(Counter(q['action'] for q in parts)),flags={k:sum(q['flags'][k]=='1' for q in parts) for k in ['Small','Occluded','Blurred','No Ball']},pending_only=True,all_require_user_review=True,labels_written_to_dataset=0,approval_flags_cleared=0,user_approved=0,canonical_dataset_written=False,reviewer='root',frozen=True)
save(W/'proposals.json',parts);save(W/'summary.json',s)
print(json.dumps({k:v for k,v in s.items() if not k.startswith('actual_')},ensure_ascii=False))
