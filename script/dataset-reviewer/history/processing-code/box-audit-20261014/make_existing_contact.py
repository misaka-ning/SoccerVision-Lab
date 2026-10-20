from pathlib import Path
from PIL import Image,ImageDraw
import json
root=Path('dataset_processing/box-audit-20261014'); out=root/'existing_contacts';out.mkdir(exist_ok=True)
rows=[r for r in json.load(open(root/'inventory.json')) if not r['filename'].startswith('video_4bec9c343db72928_')]
full=[]; crops=[]
for r in rows:
 im=Image.open(r['image_path']).convert('RGB');c=im.copy();dd=ImageDraw.Draw(c)
 for b in r['boxes']:dd.rectangle(b['xyxy'] if isinstance(b,dict) else b,outline='red',width=2)
 c.thumbnail((240,135));t=Image.new('RGB',(240,165),'#202020');t.paste(c,(0,26));d=ImageDraw.Draw(t);d.text((3,1),f"{r['index']} {r['filename']}",fill='white');d.text((3,14),f"{r['meta']['annotation_status']} {len(r['boxes'])}boxes",fill='white');full.append(t)
 for bi,b in enumerate(r['boxes']):
  b=b['xyxy'] if isinstance(b,dict) else b;p=max(10,max(b[2]-b[0],b[3]-b[1])*.25);roi=[max(0,int(b[0]-p)),max(0,int(b[1]-p)),min(im.width,int(b[2]+p+1)),min(im.height,int(b[3]+p+1))];c=im.crop(roi);scale=min(256/c.width,200/c.height);c=c.resize((round(c.width*scale),round(c.height*scale)));dd=ImageDraw.Draw(c);dd.rectangle([(b[0]-roi[0])*scale,(b[1]-roi[1])*scale,(b[2]-roi[0])*scale,(b[3]-roi[1])*scale],outline='red',width=1);t=Image.new('RGB',(256,230),'#202020');t.paste(c,(0,28));d=ImageDraw.Draw(t);d.text((3,1),f"{r['index']} {r['filename']} b{bi}",fill='white');d.text((3,14),f"{[round(v) for v in b]} {r['meta']['annotation_status'][:8]}",fill='white');crops.append((t,r['index'],bi))
for name,tiles in [('full',full),('crops',[c[0] for c in crops])]:
 mapping=[]
 count=48 if name=='full' else 24
 for start in range(0,len(tiles),count):
  ts=tiles[start:start+count];w,h=ts[0].size;c=Image.new('RGB',(w*6,h*(8 if name=='full' else 4)),'#202020')
  for j,t in enumerate(ts):c.paste(t,((j%6)*w,(j//6)*h))
  fn=f'{name}-{start//count+1:03d}.jpg';c.save(out/fn,quality=92)
  mapping.append({'page':start//count+1,'path':str((out/fn).resolve()),'items':[{'index':r['index'],'filename':r['filename']} for r in rows[start:start+count]] if name=='full' else [{'index':crops[k][1],'box_index':crops[k][2]} for k in range(start,min(len(crops),start+count))]})
 (out/f'{name}-map.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2))
print(len(rows),len(crops))
