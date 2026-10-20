import json,sys
from pathlib import Path
base=Path(__file__).parent
if len(sys.argv)>1:
 group=int(sys.argv[1]); start=int(sys.argv[2]); end=int(sys.argv[3]); reason=sys.argv[4];flags=sys.argv[5] if len(sys.argv)>5 else '0001';action=sys.argv[6] if len(sys.argv)>6 else 'keep'
 base=base.parent/f'group-{group}'
 prefix='' if group==1 else 'head-'
 p=base/(prefix+'notes.json')
 d=json.load(open(p)) if p.exists() else {'actual_opened_full_pages':[],'actual_opened_roi_pages':[],'observations':{}}
 for page in range(start,end+1):
  path=str(base/'full'/f'page-{page:03d}.png')
  if path not in d['actual_opened_full_pages']:d['actual_opened_full_pages'].append(path)
  d['observations'][str(page)]={'locals':[page*2,page*2+1],'reason':reason,'flags':flags,'action':action}
 p.write_text(json.dumps(d,ensure_ascii=False,indent=2))
