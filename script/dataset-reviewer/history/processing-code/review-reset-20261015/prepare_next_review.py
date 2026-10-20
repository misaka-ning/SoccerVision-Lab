#!/usr/bin/env python3
"""Snapshot a selected batch read-only and render native full frames and label ROIs."""
import csv,hashlib,io,json,math,sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
W=Path(__file__).resolve().parent;D=Path('/home/misaka/workspace/datasets')
sys.path.insert(0,str(W.parent/'confidence-review-20261014'));import audit_io as h
FONT=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',14)
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def main():
 batch=int(sys.argv[1]);out=W/f'batch-{batch:03d}';out.mkdir(exist_ok=False);names=(W/f'batches/batch-{batch:03d}.txt').read_text().splitlines();raw=(D/'metadata.csv').read_bytes();rows={r['图片']:r for r in h.csv_parts(raw)['rows']};old={r['filename']:r for r in json.loads((W/f'batches/batch-{batch:03d}-inventory.json').read_text())};records=[]
 for i,n in enumerate(names):
  r=rows[n];ip=h.regular_under(D/'images'/r['split']/n,D);lp=h.regular_under(D/'labels'/r['split']/(Path(n).stem+'.txt'),D);imbytes=ip.read_bytes();lb=lp.read_bytes()
  with Image.open(io.BytesIO(imbytes)) as im:w,hh=im.size
  boxes=h.label_boxes(lb,boundary_tolerance=1e-6);records.append(dict(index=i,filename=n,图片=n,split=r['split'],image_path=str(ip),label_path=str(lp),width=w,height=hh,image_sha256=h.digest(imbytes),label_sha256=h.digest(lb),label_text=lb.decode(),boxes=[dict(box_index=j,xywhn=b[1:],xyxy=[(b[1]-b[3]/2)*w,(b[2]-b[4]/2)*hh,(b[1]+b[3]/2)*w,(b[2]+b[4]/2)*hh]) for j,b in enumerate(boxes)],parse_errors=[],meta=r))
 save(out/'inventory.json',records);save(out/'metadata-snapshot.json',{'sha256':h.digest(raw),'rows':len(rows)})
 results=[]
 for g in range(4):
  folder=out/f'group-{g+1}';folder.mkdir();(folder/'full').mkdir();(folder/'roi').mkdir();recs=records[g*250:(g+1)*250];save(folder/'inventory.json',recs);full=[];units=[]
  # Every full-image page contains 2 native images, one above the other.
  for start in range(0,len(recs),2):
   rs=recs[start:start+2];width=max(r['width'] for r in rs);height=sum(r['height']+28 for r in rs);canvas=Image.new('RGB',(width,height),'#222');d=ImageDraw.Draw(canvas);top=0
   for off,r in enumerate(rs):
    d.text((3,top+3),f"n{start+off} {r['filename']} {r['width']}x{r['height']} boxes={len(r['boxes'])}",font=FONT,fill='white');im=Image.open(r['image_path']).convert('RGB');dr=ImageDraw.Draw(im)
    for b in r['boxes']:dr.rectangle(b['xyxy'],outline='#ff3030',width=1)
    canvas.paste(im,(0,top+28));top+=r['height']+28
   page=folder/'full'/f'page-{start//2:03d}.png';canvas.save(page);full.append({'path':str(page),'locals':list(range(start,min(start+2,len(recs))))})
  for n,r in enumerate(recs):
   for b in r['boxes']:
    x1,y1,x2,y2=b['xyxy'];pad=max(16,.2*max(x2-x1,y2-y1));crop=[max(0,math.floor(x1-pad)),max(0,math.floor(y1-pad)),min(r['width'],math.ceil(x2+pad)),min(r['height'],math.ceil(y2+pad))];units.append(dict(local=n,box_index=b['box_index'],crop=crop,xyxy=b['xyxy'],filename=r['filename']))
  for start in range(0,len(units),8):
   canvas=Image.new('RGB',(1120,1040),'#222');d=ImageDraw.Draw(canvas)
   for k,u in enumerate(units[start:start+8]):
    r=recs[u['local']];x=(k%2)*560;y=(k//2)*260;d.text((x+3,y+1),f"n{u['local']} b{u['box_index']} {r['filename']}",font=FONT,fill='white');d.text((x+3,y+18),'xyxy '+','.join(f'{v:.2f}' for v in u['xyxy']),font=FONT,fill='white');im=Image.open(r['image_path']).convert('RGB').crop(u['crop']);scale=min(270/im.width,218/im.height);im=im.resize((max(1,round(im.width*scale)),max(1,round(im.height*scale))),Image.Resampling.NEAREST);canvas.paste(im,(x+2,y+39));boxed=im.copy();bd=ImageDraw.Draw(boxed);x1,y1,x2,y2=u['xyxy'];cx,cy,_,_=u['crop'];bd.rectangle(((x1-cx)*scale,(y1-cy)*scale,(x2-cx)*scale,(y2-cy)*scale),outline='#ff3030');canvas.paste(boxed,(x+282,y+39));u['page']=str(folder/'roi'/f'page-{start//8:03d}.png')
   canvas.save(folder/'roi'/f'page-{start//8:03d}.png')
  save(folder/'manifest.json',dict(full=full,roi=units));result=dict(group=g+1,images=len(recs),full_pages=len(full),boxes=len(units),roi_pages=math.ceil(len(units)/8));results.append(result);print(json.dumps(result),flush=True)
 save(out/'rendered.json',results)
if __name__=='__main__':main()
