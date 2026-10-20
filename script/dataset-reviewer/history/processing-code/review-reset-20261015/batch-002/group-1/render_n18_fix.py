import json
from pathlib import Path
from PIL import Image,ImageDraw
p=Path(__file__).parent;a=json.loads((p/'inventory.json').read_text())[18];im=Image.open(a['image_path']).convert('RGB');crop=(280,190,390,300);s=4
out=Image.new('RGB',(880,470),'#222');d=ImageDraw.Draw(out)
for col,(name,b) in enumerate([('old',[298,208,363,280]),('proposed',[294,208,375,282])]):
 tile=im.crop(crop).resize((440,440),Image.Resampling.NEAREST);dt=ImageDraw.Draw(tile);dt.rectangle(tuple((v-crop[j%2])*s for j,v in enumerate(b)),outline='red',width=2);out.paste(tile,(col*440,30));d.text((col*440+2,5),name+' '+str(b),fill='white')
out.save(p/'detail-n18-before-after.png')
