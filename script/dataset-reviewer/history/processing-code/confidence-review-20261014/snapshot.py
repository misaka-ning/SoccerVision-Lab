import csv,json,hashlib,collections,datetime
from pathlib import Path
from PIL import Image
W=Path(__file__).parent;root=Path('/home/misaka/workspace/datasets');rows=list(csv.DictReader((root/'metadata.csv').open(encoding='utf-8-sig',newline='')));inventory=[];pending=[];stats=collections.Counter();(W/'baseline').mkdir(exist_ok=True);(W/'baseline/metadata.csv').write_bytes((root/'metadata.csv').read_bytes());(W/'baseline/dataset.yaml').write_bytes((root/'dataset.yaml').read_bytes())
for i,m in enumerate(rows):
 name=m['图片'];ip=root/'images'/m['split']/name;lp=root/'labels'/m['split']/(Path(name).stem+'.txt');im=Image.open(ip);text=lp.read_text(); boxes=[];errs=[]
 for num,line in enumerate(text.splitlines(),1):
  if not line.strip():continue
  try:
   s=line.split();assert len(s)==5 and s[0]=='0';x,y,bw,bh=map(float,s[1:]);a=[(x-bw/2)*im.width,(y-bh/2)*im.height,(x+bw/2)*im.width,(y+bh/2)*im.height];boxes.append({'box_index':len(boxes),'xyxy':a,'xywhn':[x,y,bw,bh],'raw_line':line})
  except Exception:errs.append(num)
 r={'index':i,'filename':name,'图片':name,'split':m['split'],'image_path':str(ip),'label_path':str(lp),'width':im.width,'height':im.height,'image_sha256':hashlib.sha256(ip.read_bytes()).hexdigest(),'label_sha256':hashlib.sha256(lp.read_bytes()).hexdigest(),'label_text':text,'boxes':boxes,'parse_errors':errs,'meta':m,'source_frame_idx':int(m['source_frame_idx']) if m.get('source_frame_idx') else None,'eye':m.get('eye')};inventory.append(r)
 if m['label_review_required']=='1' or m['scene_review_required']=='1' or m['annotation_status'] in ['auto_label_needs_review','needs_visibility_review','needs_manual_bbox_annotation']:pending.append(r)
 stats[m['annotation_status']]+=1
(W/'inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2));(W/'pending-inventory.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2));groups={}
for g in range(3):
 chunk=pending[g*len(pending)//3:(g+1)*len(pending)//3];out=W/f'group-{g+1}';out.mkdir(exist_ok=True);(out/'inventory.json').write_text(json.dumps(chunk,ensure_ascii=False,indent=2));groups[str(g+1)]={'images':len(chunk),'boxes':sum(len(r['boxes']) for r in chunk),'indices':[r['index'] for r in chunk]}
summary={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'total_images':len(rows),'pending_images':len(pending),'pending_nonempty':sum(bool(r['boxes']) for r in pending),'groups':groups,'statuses':dict(stats)};(W/'baseline-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print({k:v for k,v in summary.items() if k!='groups'});print('groups',{k:{a:b for a,b in v.items() if a!='indices'} for k,v in groups.items()})
