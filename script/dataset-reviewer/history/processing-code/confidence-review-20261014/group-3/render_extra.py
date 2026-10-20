import json,os
from PIL import Image,ImageDraw,ImageFont
D=os.path.dirname(__file__);r=json.load(open(D+'/inventory.json'));f=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',14)
ns=[216,218,220,221,222,228,503,504,561,562,633,634,775,776,1129,1130]
for p in range(4):
 c=Image.new('RGB',(1344,480),'white');d=ImageDraw.Draw(c)
 for j,n in enumerate(ns[p*4:p*4+4]):
  im=Image.open(r[n]['image_path']).convert('RGB');x=0;y=j*120;crop=im.crop((0,328,672,376)).resize((1344,96),Image.Resampling.NEAREST);c.paste(crop,(x,y+24));d.text((3,y+2),f'n{n} bottom native x2, complete width',font=f,fill='black')
 c.save(f'{D}/native/bottom-extra-{p}.png')
for n,region in [(1476,(290,230,445,335)),(1390,(280,210,460,340)),(1391,(280,210,460,340)),(106,(550,160,672,280)),(104,(540,120,672,340)),(751,(300,150,490,300)),(752,(260,150,450,300)),(753,(300,150,490,300)),(754,(260,150,450,300))]:
 im=Image.open(r[n]['image_path']).convert('RGB');crop=im.crop(region);crop=crop.resize((crop.width*4,crop.height*4),Image.Resampling.NEAREST);c=Image.new('RGB',(crop.width,crop.height+26),'white');c.paste(crop,(0,26));ImageDraw.Draw(c).text((3,2),f'n{n} native region {region} x4',font=f,fill='black');c.save(f'{D}/native/extra-{n}.png')
