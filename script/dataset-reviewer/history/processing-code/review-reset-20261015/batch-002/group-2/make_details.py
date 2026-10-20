import json, math
from PIL import Image, ImageDraw
from pathlib import Path
p=Path(__file__).parent;a=json.loads((p/'inventory.json').read_text());out=p/'details';out.mkdir(exist_ok=True)
for n in [56,130,137,138,139,140,219,246,247,248]:
 r=a[n];im=Image.open(r['image_path']).convert('RGB');x1,y1,x2,y2=r['boxes'][0]['xyxy']; pad=35;crop=(max(0,math.floor(x1)-pad),max(0,math.floor(y1)-pad),min(im.width,math.ceil(x2)+pad),min(im.height,math.ceil(y2)+pad));raw=im.crop(crop);ov=raw.copy();d=ImageDraw.Draw(ov);d.rectangle([x1-crop[0],y1-crop[1],x2-crop[0],y2-crop[1]],outline='red',width=1)
 # 2x raw/overlay for pixel-level visual decision
 canv=Image.new('RGB',(raw.width*4,raw.height*2+30),(25,25,25));d=ImageDraw.Draw(canv);d.text((4,6),f'n{n} {r["filename"]} crop={crop} box={[round(v,2) for v in [x1,y1,x2,y2]]}',fill='white');canv.paste(raw.resize((raw.width*2,raw.height*2),Image.Resampling.NEAREST),(0,30));canv.paste(ov.resize((raw.width*2,raw.height*2),Image.Resampling.NEAREST),(raw.width*2,30));canv.save(out/f'n{n:03d}.png')
s=json.loads((p/'notes.json').read_text());s['roi_pages']+=list(range(29,32));(p/'notes.json').write_text(json.dumps(s,ensure_ascii=False,indent=2))
