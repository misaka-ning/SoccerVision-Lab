import json
from pathlib import Path
P=Path(__file__).parent
inv=json.loads((P/'inventory.json').read_text());m=json.loads((P/'manifest.json').read_text())
f=P/'review-notes.json'
notes=json.loads(f.read_text()) if f.exists() else {'full_pages':[],'roi_pages':[],'details':[],'observations':{}}
def save(): f.write_text(json.dumps(notes,ensure_ascii=False,indent=2))
def full(pages,observations):
 for p in pages:
  if p not in notes['full_pages']:notes['full_pages'].append(p)
 for k,v in observations.items():notes['observations'][str(k)]=v
 save()
def roi(pages):
 for p in pages:
  if p not in notes['roi_pages']:notes['roi_pages'].append(p)
 save()
if __name__=='__main__':
 full(list(range(8)),{i:{'flags':['0' if i<4 or i>=8 else '1','1','1' if i<2 else '0','0'],'reason':'纸箱下方黑白足球可见；箱体覆盖上缘；原生全景确认仅此一个球，框覆盖可见球。'+('整图与球面有运动拖影。' if i<2 else '没有明显运动拖影。'),'certain':False if 2<=i<=7 else True} for i in range(16)})
