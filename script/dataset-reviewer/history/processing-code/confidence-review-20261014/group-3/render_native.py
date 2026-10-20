import json,os,math
from PIL import Image,ImageDraw,ImageFont
D=os.path.dirname(__file__);r=json.load(open(D+'/inventory.json'));os.makedirs(D+'/native',exist_ok=True)
f=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',14)
ns=[i for i,x in enumerate(r) if not x['boxes']];mapping={}
for p in range(math.ceil(len(ns)/4)):
 c=Image.new('RGB',(1344,800),'#eeeeee');d=ImageDraw.Draw(c)
 for j,n in enumerate(ns[p*4:p*4+4]):
  x=(j%2)*672;y=(j//2)*400;im=Image.open(r[n]['image_path']).convert('RGB');c.paste(im,(x,y+24));d.text((x+4,y+3),f'n{n} i{r[n]["index"]} native full {r[n]["filename"][-26:]}',fill='black',font=f);mapping[str(n)]=f'{D}/native/empty-{p:02d}.png'
 c.save(f'{D}/native/empty-{p:02d}.png')
json.dump(mapping,open(D+'/native-map.json','w'),indent=2)
for n in [138,301,418,106,1390,1391]:
 row=r[n];im=Image.open(row['image_path']).convert('RGB');b=row['boxes'][0]['xyxy'];x1,y1,x2,y2=b;pad=20;box=(max(0,math.floor(x1-pad)),max(0,math.floor(y1-pad)),min(im.width,math.ceil(x2+pad)),min(im.height,math.ceil(y2+pad)));raw=im.crop(box);s=min(5,640/raw.width,600/raw.height);raw=raw.resize((round(raw.width*s),round(raw.height*s)),Image.Resampling.NEAREST);over=raw.copy();dd=ImageDraw.Draw(over);dd.rectangle(((x1-box[0])*s,(y1-box[1])*s,(x2-box[0])*s,(y2-box[1])*s),outline='red',width=2);c=Image.new('RGB',(raw.width*2,raw.height+40),'white');c.paste(raw,(0,40));c.paste(over,(raw.width,40));ImageDraw.Draw(c).text((5,5),f'n{n} raw native zoom | current box {x2-x1:.1f}x{y2-y1:.1f}px',fill='black',font=f);c.save(f'{D}/native/detail-{n}.png')
