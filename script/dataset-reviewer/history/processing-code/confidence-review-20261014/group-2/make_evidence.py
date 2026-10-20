from PIL import Image,ImageDraw,ImageFont
import json,math,pathlib
base=pathlib.Path(__file__).parent
xs=json.load(open(base/'inventory.json'))
font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13)
for p in range(math.ceil(len(xs)/48)):
 c=Image.new('RGB',(1920,8*210),'#dddddd');d=ImageDraw.Draw(c)
 for z,x in enumerate(xs[p*48:(p+1)*48]):
  im=Image.open(x['image_path']).convert('RGB');dd=ImageDraw.Draw(im)
  for b in x['boxes']: dd.rectangle(b['xyxy'],outline='#ff2020',width=1)
  im=im.resize((320,179))
  cx=(z%6)*320;cy=(z//6)*210;c.paste(im,(cx,cy));m=x['meta']
  d.text((cx+3,cy+180),f"#{p*48+z} idx{x['index']} f{x['source_frame_idx']} {x['eye']} b{len(x['boxes'])}",font=font,fill='black')
  d.text((cx+3,cy+195),f"S{m['Small']} O{m['Occluded']} B{m['Blurred']} N{m['No Ball']}",font=font,fill='black')
 c.save(base/f'scene_{p+1:02d}.jpg',quality=95)
bs=[(i,x,b) for i,x in enumerate(xs) for b in x['boxes']]
manifest=[]
for p in range(math.ceil(len(bs)/24)):
 c=Image.new('RGB',(1280,6*250),'#dddddd');d=ImageDraw.Draw(c)
 for z,(i,x,b) in enumerate(bs[p*24:(p+1)*24]):
  im=Image.open(x['image_path']).convert('RGB');box=b['xyxy'];cx0=(box[0]+box[2])/2;cy0=(box[1]+box[3])/2
  rw=max(140,math.ceil(box[2]-box[0])+60);rh=max(140,math.ceil(box[3]-box[1])+60)
  left=max(0,min(x['width']-rw,int(cx0-rw/2)));top=max(0,min(x['height']-rh,int(cy0-rh/2)));right=min(x['width'],left+rw);bottom=min(x['height'],top+rh)
  cr=im.crop((left,top,right,bottom));dr=ImageDraw.Draw(cr);dr.rectangle([box[0]-left,box[1]-top,box[2]-left,box[3]-top],outline='#ff2020',width=1)
  # Native pixels (or 2x nearest for small crops), never downscale ball edges.
  scale=2 if cr.width<=155 and cr.height<=105 else 1
  if scale==2:cr=cr.resize((cr.width*2,cr.height*2),Image.Resampling.NEAREST)
  ox=(z%4)*320+(320-cr.width)//2;oy=(z//4)*250+5;c.paste(cr,(ox,oy));m=x['meta']
  d.text(((z%4)*320+3,(z//4)*250+212),f"#{i} idx{x['index']} f{x['source_frame_idx']} {x['eye']}",font=font,fill='black')
  d.text(((z%4)*320+3,(z//4)*250+229),f"{box[2]-box[0]:.1f}x{box[3]-box[1]:.1f} S{m['Small']} O{m['Occluded']} B{m['Blurred']} native",font=font,fill='black')
  manifest.append({'local':i,'roi_page':p+1,'cell':z,'crop':[left,top,right,bottom]})
 c.save(base/f'roi_{p+1:02d}.png')
json.dump(manifest,open(base/'roi_manifest.json','w'),indent=2)
