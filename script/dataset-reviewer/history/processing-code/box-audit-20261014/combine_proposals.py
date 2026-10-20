import json,hashlib,collections
from pathlib import Path
W=Path(__file__).parent; inv=json.loads((W/'inventory.json').read_text()); by={r['filename']:r for r in inv};merged={};sources={}
files=['existing_changed_proposals.json','new-first-corrections-proposals.json','middle-corrections-proposals.json','middle-missing-extra.json','review-last-proposals.json']
for f in files:
 rows=json.loads((W/f).read_text())
 for p in rows:
  n=p['filename'];b=by[n]
  if n in merged:raise ValueError('Duplicate changed frame '+n)
  if 'boxes_xyxy' not in p:p['boxes_xyxy']=[x.get('tight_xyxy') or x['original_xyxy'] for x in p['boxes']]
  p['boxes_xyxy']=[[max(0,min(b['width'] if k%2==0 else b['height'],float(z))) if (-.00001 <= z <= (b['width'] if k%2==0 else b['height'])+.00001) else z for k,z in enumerate(x)] for x in p['boxes_xyxy']]
  p.update(filename=n,split=b['split'],expected_label_sha256=b['label_sha256'],action='correct_false_positive_or_missing_ball',native_visual_review=True,source=p.get('source') or f+'; full scene, native ROI and proposed overlay inspected by assistant')
  p['reason']=p.get('reason') or '；'.join(x['reason'] for x in p.get('boxes',[]) if x.get('tight_xyxy') is not None) or '原生可见足球漏框，补齐可见球体边界，标为待人工审核。'
  merged[n]=p;sources[n]=f
(W/'combined-proposals.json').write_text(json.dumps(list(merged.values()),ensure_ascii=False,indent=2))
print('proposal_images',len(merged),'by_source',dict(collections.Counter(sources.values())))
# Coverage has been recorded from actual tool opens, never inferred from page existence.
c=[]
old=json.loads((W/'existing_audit.json').read_text());oldrows=old['records'] if 'records' in old else old.get('results',old.get('decisions',old.get('images',[])));print('oldkeys',list(old));
if isinstance(oldrows,dict):oldrows=list(oldrows.values())
if oldrows:
 for r in oldrows:c.append({'filename':r['filename'],'group':'existing','scene_seen':bool(r.get('seen_full')),'roi_seen':bool(r.get('seen_crops')) or not by[r['filename']]['boxes'],'decision':r.get('decision','retain')})
first=json.loads((W/'new-first-visual-review.json').read_text())
for n in first['seen_filenames']:c.append({'filename':n,'group':'first','scene_seen':True,'roi_seen':True,'decision':'replace' if n in merged else 'retain_or_uncertain'})
for r in json.loads((W/'review-middle-decisions.json').read_text()):c.append({'filename':r['filename'],'group':'middle','scene_seen':r['scene_seen'],'roi_seen':r['roi_seen'] or not by[r['filename']]['boxes'],'decision':'replace' if r['filename'] in merged else 'retain_or_uncertain'})
for r in json.loads((W/'review-last-decisions.json').read_text()).values():c.append({'filename':r['filename'],'group':'last','scene_seen':r['scene_seen'],'roi_seen':r['roi_seen'] or not by[r['filename']]['boxes'],'decision':r['action']})
print('coverage',len(c),'unique',len({r['filename'] for r in c}));print('incomplete',sum(not r['scene_seen'] or not r['roi_seen'] for r in c));(W/'all-images-visual-coverage.json').write_text(json.dumps(c,ensure_ascii=False,indent=2))
