from PIL import Image,ImageDraw
from pathlib import Path
import json
r=json.load(open('dataset_processing/box-audit-20261014/existing_inventory_initial.json'))
s=[x for x in r if x['boxes'] and x['meta']['annotation_status'] in ('auto_label_needs_review','reviewed_annotation')]
s=sorted(s,key=lambda x:max(max(b[2]-b[0],b[3]-b[1])/max(1,min(b[2]-b[0],b[3]-b[1])) for b in x['boxes']),reverse=True)
s=s[:12]+[x for x in r if x['filename'] in ('legacy_train_000488.jpg','legacy_train_000492.jpg','legacy_train_000484.jpg','legacy_train_000481.jpg')]
w=1600;cw=400;ch=400;out=Image.new('RGB',(w,((len(s)+3)//4)*ch),'#202020');d=ImageDraw.Draw(out)
for i,x in enumerate(s):
 b=x['boxes'][0];im=Image.open(x['path']);p=40;roi=[max(0,int(b[0])-p),max(0,int(b[1])-p),min(im.width,int(b[2])+p),min(im.height,int(b[3])+p)]
 crop=im.crop(roi); dd=ImageDraw.Draw(crop);dd.rectangle((b[0]-roi[0],b[1]-roi[1],b[2]-roi[0],b[3]-roi[1]),outline='red',width=1);crop.thumbnail((400,360));xx=i%4*cw;yy=i//4*ch;out.paste(crop,(xx,yy+40));d.text((xx+3,yy+2),x['filename'],fill='white');d.text((xx+3,yy+17),f'{[round(v) for v in b]} {x["meta"]["annotation_status"][:8]}',fill='white')
out.save('dataset_processing/box-audit-20261014/existing-pilot.png')
Path('dataset_processing/box-audit-20261014/existing-pilot-map.json').write_text(json.dumps(s,ensure_ascii=False))
