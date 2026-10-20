from PIL import Image,ImageDraw
import json,sys
from pathlib import Path
R=Path('dataset_processing/box-audit-20261014');rows=json.load(open(R/'inventory.json'));ids=list(map(int,sys.argv[2:]));out=Image.new('RGB',(400*4,360*((len(ids)+3)//4)),'#202020');d=ImageDraw.Draw(out)
for j,i in enumerate(ids):
 r=rows[i];im=Image.open(r['image_path']).convert('RGB');b=r['boxes'][0]['xyxy'] if r['boxes'] else [0,0,r['width'],r['height']];p=12;roi=[max(0,int(b[0])-p),max(0,int(b[1])-p),min(im.width,int(b[2])+p+1),min(im.height,int(b[3])+p+1)];c=im.crop(roi);sc=min(395/c.width,320/c.height);c=c.resize((round(c.width*sc),round(c.height*sc)),Image.Resampling.NEAREST);dd=ImageDraw.Draw(c)
 for x in range((roi[0]//5+1)*5,roi[2],5):dd.line(((x-roi[0])*sc,0,(x-roi[0])*sc,6),fill='yellow',width=1);dd.text(((x-roi[0])*sc,7),str(x),fill='yellow')
 for y in range((roi[1]//5+1)*5,roi[3],5):dd.line((0,(y-roi[1])*sc,6,(y-roi[1])*sc),fill='yellow',width=1);dd.text((7,(y-roi[1])*sc),str(y),fill='yellow')
 dd.rectangle([(b[0]-roi[0])*sc,(b[1]-roi[1])*sc,(b[2]-roi[0])*sc,(b[3]-roi[1])*sc],outline='red',width=1);xx=j%4*400;yy=j//4*360;out.paste(c,(xx,yy+36));d.text((xx+3,yy+2),f"{i} {r['filename']}",fill='white');d.text((xx+3,yy+17),f"roi {roi} scale{sc:.3f}",fill='white')
out.save(R/sys.argv[1])
