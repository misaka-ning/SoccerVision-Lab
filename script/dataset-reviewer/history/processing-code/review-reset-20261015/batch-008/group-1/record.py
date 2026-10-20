import json
from pathlib import Path
W=Path(__file__).resolve().parent
P=W/'notes.json'
def record(full=(),roi=(),rows=()):
 d=json.loads(P.read_text()) if P.exists() else {'actual_opened_full_pages':[],'actual_opened_roi_pages':[],'observations':{}}
 for key,nums,folder in [('actual_opened_full_pages',full,'full'),('actual_opened_roi_pages',roi,'roi')]:
  for n in nums:
   path=str(W/folder/f'page-{n:03}.png')
   if path not in d[key]: d[key].append(path)
 for r in rows:
  i,flags,reason,*extra=r
  d['observations'][str(i)]={'flags':dict(zip(('Small','Occluded','Blurred','No Ball'),flags)),'reason':reason,**(extra[0] if extra else {})}
 P.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
