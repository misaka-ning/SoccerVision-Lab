import json,sys
from pathlib import Path
p=Path(__file__).parent
f=p/'notes.json'
d=json.loads(f.read_text()) if f.exists() else {'opened_full':[],'opened_roi':[],'observations':[]}
u=json.loads(sys.stdin.read())
for k in ('opened_full','opened_roi'):d[k]=sorted(set(d[k]+u.get(k,[])))
d['observations']+=u.get('observations',[])
f.write_text(json.dumps(d,ensure_ascii=False,indent=2))
