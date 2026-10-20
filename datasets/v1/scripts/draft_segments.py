from common import *

specs=[
 ('S01',62,107,55,120,'Camera handling, people/ceiling and no-ball transition'),
 ('S02',211,253,201,265,'First floor-level ball approach and shoe-side rolling'),
 ('S03',312,349,303,361,'Red-shirt operator, rolling ball and robot crossing'),
 ('S04',504,540,494,552,'Far-ball tracking with person crossing in foreground'),
 ('S05',644,670,636,680,'Far robot and ball, low-angle occlusion/absence transition'),
 ('S06',752,781,741,794,'Ball and shoes near shelf; rapid viewpoint change'),
 ('S07',1117,1152,1105,1166,'Fast close ball / feet interaction with motion blur'),
 ('S08',1464,1518,1453,1531,'Distant-to-near ball pass and multiple shoe interactions'),
 ('S09',1584,1619.6,1572,1619.6,'Exit and glass-door negative sequence'),
]
rows=load(ROOT/'analysis/source_inventory.json');vv=[r for r in rows if r['source']=='181531' and not r['excluded']]
groups=defaultdict(list)
for r in vv:groups[r['frame']].append(r)
timeline=[next((r for r in groups[f] if r['eye']=='left'),groups[f][0]) for f in sorted(groups)]
segments=[];pages=[]
for sid,start,end,outer0,outer1,desc in specs:
 rr=[]
 for t in np.arange(max(0,outer0-6),min(1619.6,outer1+6)+.1,2):
  r=dict(min(timeline,key=lambda r:abs(r['seconds']-t)))
  if rr and r['frame']==rr[-1]['frame']:continue
  r['display_role']='CORE' if start<=r['seconds']<=end else 'BUFF' if outer0<=r['seconds']<=outer1 else 'TRAIN'
  rr.append(r)
 page=contact(rr,ROOT/f'evidence/draft-{sid}.jpg',f'{sid} draft {stamp(start)}-{stamp(end)} / CORE+BUFF held out / surrounding TRAIN',cols=6,tile_w=224,tile_h=126)
 pages.append(page)
 core=[r for r in vv if start<=r['seconds']<=end]
 expanded=[r for r in vv if outer0<=r['seconds']<=outer1]
 segments.append(dict(segment_id=sid,start_seconds=start,end_seconds=end,buffer_start_seconds=outer0,buffer_end_seconds=outer1,
  description=desc,candidate_images=len(core),candidate_source_moments=len({r['frame'] for r in core}),buffer_images=len(expanded)-len(core),
  flags={k:sum(r['flags'][k] for r in core) for k in FLAGS},evidence_page=page['path'],status='DRAFT_PENDING_ACTUAL_VISUAL_INSPECTION'))
save(ROOT/'analysis/draft_segments.json',segments);save(ROOT/'analysis/draft_contact_pages.json',pages)
print(json.dumps(segments,ensure_ascii=False,indent=2))
