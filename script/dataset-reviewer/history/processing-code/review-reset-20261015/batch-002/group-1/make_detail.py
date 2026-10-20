import json
from pathlib import Path
from PIL import Image,ImageDraw
p=Path(__file__).parent;a=json.loads((p/'inventory.json').read_text())
for i,crop,s in [(249,(510,135,920,550),2),(18,(285,195,377,294),5),(16,(272,215,359,300),5)]:
 im=Image.open(a[i]['image_path']).convert('RGB').crop(crop).resize(((crop[2]-crop[0])*s,(crop[3]-crop[1])*s),Image.Resampling.NEAREST);d=ImageDraw.Draw(im)
 for x in range((crop[0]//10+1)*10,crop[2],10):
  xx=(x-crop[0])*s;d.line((xx,0,xx,im.height),fill=(0,120,80),width=1);d.text((xx+1,2),str(x),fill='yellow')
 for y in range((crop[1]//10+1)*10,crop[3],10):
  yy=(y-crop[1])*s;d.line((0,yy,im.width,yy),fill=(0,120,80),width=1);d.text((2,yy),str(y),fill='yellow')
 im.save(p/f'detail-n{i}.png')
