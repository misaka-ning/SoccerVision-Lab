from PIL import Image,ImageDraw,ImageFont
import json,pathlib,sys,math
b=pathlib.Path(__file__).parent;x=json.load(open(b/'inventory.json'));font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',15)
ids=list(map(int,sys.argv[2:]));name=sys.argv[1]
for p in range(math.ceil(len(ids)/6)):
 c=Image.new('RGB',(1344,3*405),'#ddd');d=ImageDraw.Draw(c)
 for z,i in enumerate(ids[p*6:(p+1)*6]):
  im=Image.open(x[i]['image_path']).convert('RGB');dd=ImageDraw.Draw(im)
  for bb in x[i]['boxes']:dd.rectangle(bb['xyxy'],outline='red',width=1)
  cx=(z%2)*672;cy=(z//2)*405;c.paste(im,(cx,cy));d.text((cx+3,cy+378),f"#{i} idx{x[i]['index']} f{x[i]['source_frame_idx']} {x[i]['eye']}",fill='black',font=font)
 c.save(b/f'native_{name}_{p+1:02d}.png')
