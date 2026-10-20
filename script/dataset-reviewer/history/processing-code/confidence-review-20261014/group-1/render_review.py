import json,os,math
from PIL import Image,ImageDraw,ImageFont
D=os.path.dirname(__file__); rows=json.load(open(D+'/inventory.json'));os.makedirs(D+'/full',exist_ok=True);os.makedirs(D+'/roi',exist_ok=True)
font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',14);font2=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',12)
for p in range(math.ceil(len(rows)/48)):
 canvas=Image.new('RGB',(6*448,8*282),'#f2f2f2');d=ImageDraw.Draw(canvas)
 for j,r in enumerate(rows[p*48:p*48+48]):
  n=p*48+j;x=(j%6)*448;y=(j//6)*282;im=Image.open(r['image_path']).convert('RGB');im.thumbnail((448,251));canvas.paste(im,(x,y+31));d.text((x+3,y+1),f"n{n}  i{r['index']}  {r['filename'][-40:]}",fill='black',font=font2);d.text((x+3,y+15),''.join(k[0]+r['meta'][k]+' ' for k in ['Small','Occluded','Blurred','No Ball'])+f" boxes={len(r['boxes'])} L{r['meta']['label_review_required']}",fill='black',font=font2)
 canvas.save(f'{D}/full/page-{p:02d}.jpg',quality=95)
for p in range(math.ceil(len(rows)/24)):
 canvas=Image.new('RGB',(4*330,6*266),'#e8e8e8');d=ImageDraw.Draw(canvas)
 for j,r in enumerate(rows[p*24:p*24+24]):
  n=p*24+j;x=(j%4)*330;y=(j//4)*266;im=Image.open(r['image_path']).convert('RGB')
  text=f"n{n} i{r['index']} {r['filename'][-28:]}"
  d.text((x+3,y+2),text,fill='black',font=font2)
  d.text((x+3,y+18),''.join(k[0]+r['meta'][k]+' ' for k in ['Small','Occluded','Blurred','No Ball'])+f" L{r['meta']['label_review_required']}",fill='black',font=font)
  if not r['boxes']:
   crop=im.copy();crop.thumbnail((326,230));canvas.paste(crop,(x+2,y+34));d.text((x+3,y+246),'NO CURRENT BOX',fill='darkred',font=font)
  else:
   for b,box in enumerate(r['boxes']):
    xx1,yy1,xx2,yy2=box['xyxy'];sz=max(80,xx2-xx1+28,yy2-yy1+28);cx=(xx1+xx2)/2;cy=(yy1+yy2)/2
    px1=max(0,math.floor(cx-sz/2));py1=max(0,math.floor(cy-sz/2));px2=min(im.width,math.ceil(cx+sz/2));py2=min(im.height,math.ceil(cy+sz/2))
    crop=im.crop((px1,py1,px2,py2));cw=(326//len(r['boxes']));crop.thumbnail((cw,205));scale=crop.width/(px2-px1);crop=crop.resize((round((px2-px1)*scale),round((py2-py1)*scale)))
    # render at 2.5x on small crops, limited to tile width
    scale=min(cw/(px2-px1),205/(py2-py1));crop=im.crop((px1,py1,px2,py2)).resize((round((px2-px1)*scale),round((py2-py1)*scale)),Image.Resampling.NEAREST)
    dd=ImageDraw.Draw(crop);dd.rectangle(((xx1-px1)*scale,(yy1-py1)*scale,(xx2-px1)*scale,(yy2-py1)*scale),outline='#ff3030',width=1)
    canvas.paste(crop,(x+2+b*cw,y+36));d.text((x+3,y+243),f"box {b}: {xx2-xx1:.1f}×{yy2-yy1:.1f} px",fill='black',font=font)
 canvas.save(f'{D}/roi/page-{p:02d}.png')
json.dump({'full_pages':32,'roi_pages':64,'items':len(rows)},open(D+'/rendered.json','w'),indent=2)
