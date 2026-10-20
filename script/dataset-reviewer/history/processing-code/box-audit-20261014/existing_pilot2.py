from PIL import Image,ImageDraw
import json,random
from pathlib import Path
r=json.load(open('dataset_processing/box-audit-20261014/existing_inventory_initial.json'))
s=[x for x in r if x['boxes'] and x['meta']['annotation_status']=='auto_label_needs_review'][:48]
out=Image.new('RGB',(1600,1800),'#202020');d=ImageDraw.Draw(out)
for i,x in enumerate(s):
 b=x['boxes'][0];im=Image.open(x['path']);p=max(15,int(max(b[2]-b[0],b[3]-b[1])*.35));roi=[max(0,int(b[0])-p),max(0,int(b[1])-p),min(im.width,int(b[2])+p),min(im.height,int(b[3])+p)];crop=im.crop(roi)
 scale=min(265/crop.width,260/crop.height);crop=crop.resize((round(crop.width*scale),round(crop.height*scale)));dd=ImageDraw.Draw(crop);dd.rectangle(tuple((v-roi[j%2])*scale for j,v in enumerate(b)),outline='red',width=1);xx=i%6*266;yy=i//6*225;out.paste(crop,(xx,yy+35));d.text((xx+3,yy+2),x['filename'],fill='white');d.text((xx+3,yy+17),f'{i} {[round(v) for v in b]}',fill='white')
out.save('dataset_processing/box-audit-20261014/existing-pilot2.png');Path('dataset_processing/box-audit-20261014/existing-pilot2-map.json').write_text(json.dumps(s))
