"""Render native candidate diagnostics in group-4; no dataset writes."""
import json, math, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
W = Path(__file__).resolve().parent / 'group-4'
n = int(sys.argv[1]); bb = list(map(int, sys.argv[2:6])); assert len(bb)==4
b = json.loads((W/'inventory.json').read_text())[n]
assert 0 <= bb[0] < bb[2] <= b['width'] and 0 <= bb[1] < bb[3] <= b['height']
im = Image.open(b['image_path']).convert('RGB')
font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',12)
xs=[bb[0],bb[2]]+[v['xyxy'][i] for v in b['boxes'] for i in [0,2]]
ys=[bb[1],bb[3]]+[v['xyxy'][i] for v in b['boxes'] for i in [1,3]]
c=[max(0,math.floor(min(xs)-20)),max(0,math.floor(min(ys)-20)),min(b['width'],math.ceil(max(xs)+20)),min(b['height'],math.ceil(max(ys)+20))]
s=4; z=im.crop(c).resize(((c[2]-c[0])*s,(c[3]-c[1])*s),Image.Resampling.NEAREST); d=ImageDraw.Draw(z)
for x in range(math.ceil(c[0]/10)*10,c[2],10):
 xx=(x-c[0])*s;d.line((xx,0,xx,z.height),fill='#888');d.text((xx+1,0),str(x),font=font,fill='yellow')
for y in range(math.ceil(c[1]/10)*10,c[3],10):
 yy=(y-c[1])*s;d.line((0,yy,z.width,yy),fill='#888');d.text((0,yy+1),str(y),font=font,fill='yellow')
z.save(W/f'root-grid-{n:03d}.png')
canvas=Image.new('RGB',(im.width*2,im.height+28),'#222'); d=ImageDraw.Draw(canvas)
for j,boxes in enumerate([[v['xyxy'] for v in b['boxes']],[bb]]):
 v=im.copy();vd=ImageDraw.Draw(v)
 for box in boxes:vd.rectangle(box,outline='red' if j==0 else '#00ff00',width=1)
 canvas.paste(v,(j*im.width,28));d.text((j*im.width+2,4),('BEFORE' if j==0 else 'AFTER '+str(bb)),font=font,fill='white')
canvas.save(W/f'root-before-after-{n:03d}.png')
