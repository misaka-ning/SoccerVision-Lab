#!/usr/bin/env python3
"""Combine complete visual prechecks; reads the canonical dataset only."""
import json
from collections import Counter
from pathlib import Path
P=Path(__file__).resolve().parent.parent/'review-reset-20261015/batch-002'
def read(p):return json.loads(p.read_text())
def save(p,o):p.write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n')
base=read(P/'inventory.json');byname={b['filename']:b for b in base};allq=[];groups=[]
for g in range(1,5):
 d=P/f'group-{g}';inv=read(d/'inventory.json');qs=read(d/'proposals.json');m=read(d/'manifest.json')
 if g==4:
  rn=read(d/'root-notes.json');t=read(d/'tail-summary.json')
  opened_full=[m['full'][n]['path'] for n in rn['opened_full']]+t['actual_opened_full_pages']
  opened_roi=[str(d/'roi'/f'page-{n:03d}.png') for n in rn['opened_roi']]+t['actual_opened_roi_pages']
  opened_full=sorted(set(opened_full));opened_roi=sorted(set(opened_roi))
  save(d/'summary.json',dict(images_reviewed=250,existing_boxes_reviewed=sum(len(b['boxes']) for b in inv),actual_opened_full_pages=opened_full,actual_opened_roi_pages=opened_roi,uncertain_images=sum(q['confidence']=='uncertain' for q in qs),labels_written_to_dataset=0,approval_flags_cleared=0))
 else:
  s=read(d/'summary.json')
  opened_full=s.get('actual_opened_full_pages',s.get('all_full_pages_opened',s.get('opened_full')))
  opened_roi=s.get('actual_opened_roi_pages',s.get('all_roi_pages_opened',s.get('opened_roi')))
 assert set(opened_full)=={x['path'] for x in m['full']},g
 assert set(opened_roi)=={x['page'] for x in m['roi']},g
 assert len(qs)==len(inv)==250 and len(set(q['filename'] for q in qs))==250,g
 for n,(b,q) in enumerate(zip(inv,qs)):
  assert b['filename']==q['filename'] and b['index']==q['index'],(g,n,'index')
  assert q['scene_seen'] is True and q['roi_boxes_seen']==[x['box_index'] for x in b['boxes']],(g,n,'coverage')
  required={m['full'][n//2]['path']}|{x['page'] for x in m['roi'] if x['local']==n}
  assert required<=set(q['evidence']),(g,n,'evidence')
  assert all(Path(x).is_file() for x in q['evidence']),(g,n,'missing evidence')
  assert q['expected_image_sha256']==b['image_sha256'] and q['expected_label_sha256']==b['label_sha256']
  assert set(q['flags'])=={'Small','Occluded','Blurred','No Ball'} and set(q['flags'].values())<={'0','1'}
  assert q['confidence'] in ('high','uncertain') and isinstance(q['scene_certain'],bool)
  assert q['reason'].strip()
 allq.extend(qs)
 groups.append(dict(group=g,images=250,boxes=sum(len(b['boxes']) for b in inv),full_pages=len(opened_full),roi_pages=len(opened_roi),actions=dict(Counter(q['action'] for q in qs)),uncertain=sum(q['confidence']=='uncertain' for q in qs)))
assert [q['filename'] for q in allq]==[b['filename'] for b in base]
assert len(allq)==1000 and len({q['filename'] for q in allq})==1000
save(P/'proposals.json',allq)
priority=[q['filename'] for q in allq if q['confidence']=='uncertain' or q['action'].startswith('needs_')]
priority_path=P.parent/'batches/batch-002-priority.txt'
if priority_path.exists():assert priority_path.read_text().splitlines()==priority
else:priority_path.write_text('\n'.join(priority)+'\n')
summary=dict(images=1000,boxes=sum(len(b['boxes']) for b in base),full_pages=sum(x['full_pages'] for x in groups),roi_pages=sum(x['roi_pages'] for x in groups),groups=groups,actions=dict(Counter(q['action'] for q in allq)),uncertain=sum(q['confidence']=='uncertain' for q in allq),priority=len(priority),scene_rows_changed=sum(any(q['flags'][k]!=byname[q['filename']]['meta'][k] for k in q['flags']) for q in allq),flags={k:sum(q['flags'][k]=='1' for q in allq) for k in allq[0]['flags']},all_require_user_review=True)
save(P/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
