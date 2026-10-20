from PIL import Image,ImageDraw,ImageFont
import json,os,math
D=os.path.dirname(__file__);rs=json.load(open(D+'/inventory.json'));font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',16);os.makedirs(D+'/empty-native',exist_ok=True)
empty=[(n,r) for n,r in enumerate(rs) if not r['boxes']];maps=[]
for p in range(math.ceil(len(empty)/6)):
 c=Image.new('RGB',(1344,1200),'#eee');d=ImageDraw.Draw(c);ns=[]
 for j,(n,r) in enumerate(empty[p*6:p*6+6]):
  x=(j%2)*672;y=(j//2)*400;im=Image.open(r['image_path']).convert('RGB');c.paste(im,(x,y+24));d.text((x+3,y+2),f"n{n} i{r['index']} {r['filename'][-43:]}",fill='black',font=font);ns.append(n)
 path=f'{D}/empty-native/page-{p:02d}.png';c.save(path);maps.append({'page':p,'n':ns,'path':os.path.abspath(path)})
json.dump(maps,open(D+'/empty-native/map.json','w'),indent=2)
