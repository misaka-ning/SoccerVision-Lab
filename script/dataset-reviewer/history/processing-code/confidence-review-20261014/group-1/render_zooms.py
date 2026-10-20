from PIL import Image,ImageDraw,ImageFont
import json,math,os
D=os.path.dirname(__file__);rs=json.load(open(D+'/inventory.json'));os.makedirs(D+'/zooms',exist_ok=True);font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',16)
groups=[[1200,1212,1306,1314,1350,1360,1370,1380],[0,1,591,592,593,594],[605,606,607,608,611,612],[697,822,823,824,890,891],[1157,1159,1163,1165,1226,1227,1228,1229]]
for p,ns in enumerate(groups):
 c=Image.new('RGB',(3*420,3*350),'#eee');d=ImageDraw.Draw(c)
 for j,n in enumerate(ns):
  r=rs[n];im=Image.open(r['image_path']).convert('RGB');x=(j%3)*420;y=(j//3)*350;d.text((x+4,y+2),f"n{n} {r['filename'][-30:]}",fill='black',font=font)
  if r['boxes']:
   b=r['boxes'][0]['xyxy'];cx=(b[0]+b[2])/2;cy=(b[1]+b[3])/2;sz=72;roi=(math.floor(cx-sz/2),math.floor(cy-sz/2),math.ceil(cx+sz/2),math.ceil(cy+sz/2))
  elif n in [0,1]: roi=(440,245,672,376)
  elif n in [591,592,593,594]:roi=(220,190,320,300)
  elif n in [605,606,607,608]:roi=(275,260,370,365)
  elif n in [611,612]:roi=(550,0,672,160)
  elif n==697:roi=(230,120,430,250)
  elif n in [822,823,824]:roi=(390,285,672,376)
  elif n in [890,891]:roi=(290,155,465,285)
  elif n in [1157,1159,1163,1165]:roi=(0,240,125,340)
  elif n in [1226,1227,1228,1229]:roi=(260,250,440,376)
  crop=im.crop(roi);scale=min(410/crop.width,312/crop.height);crop=crop.resize((round(crop.width*scale),round(crop.height*scale)),Image.Resampling.NEAREST);dd=ImageDraw.Draw(crop)
  for b in r['boxes']:
   a=b['xyxy'];dd.rectangle(((a[0]-roi[0])*scale,(a[1]-roi[1])*scale,(a[2]-roi[0])*scale,(a[3]-roi[1])*scale),outline='red',width=1)
  c.paste(crop,(x+3,y+30));d.text((x+4,y+327),str(roi),fill='black',font=font)
 c.save(f'{D}/zooms/page-{p:02d}.png')
json.dump(groups,open(D+'/zooms/map.json','w'))
