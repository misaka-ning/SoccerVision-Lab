#!/usr/bin/env python3
"""Render a read-only numbered contact sheet from a fixed football review group.

Run with the local Pillow runtime, e.g.:
/opt/VisionStudio/runtime/bin/python script/dataset-reviewer/render_football_review_grid.py --batch 1 --group 1
"""
import argparse,csv,hashlib,io,json,math,sys
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

W=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(W/'script'))
from common.dataset_config import load_dataset,review_records
FONTPATH='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
def font(size):return ImageFont.truetype(FONTPATH,size)
def digest(data):return hashlib.sha256(data).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',required=True,type=int);p.add_argument('--group',required=True,type=int);a=p.parse_args();selected=load_dataset();root=selected['root'];work=review_records(selected);folder=work/'batches'/f'batch-{a.batch:03d}-remaining-50';manifest=json.loads((folder/'manifest.json').read_text());item=next((g for g in manifest['groups'] if g['group']==a.group),None)
 if item is None:raise SystemExit('找不到该组')
 listpath=folder/item['file'];listdata=listpath.read_bytes()
 if digest(listdata)!=item['sha256']:raise SystemExit('固定组名单校验不一致')
 names=listdata.decode('utf-8').splitlines();raw=(root/'metadata.csv').read_bytes();rows={r['图片']:r for r in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline=''))};records=[];cards=[]
 cw,ch=448,330
 for idx,name in enumerate(names,1):
  r=rows[name];imagepath=root/'images'/r['split']/name;labelpath=root/'labels'/r['split']/(Path(name).stem+'.txt');imagebytes=imagepath.read_bytes();lb=labelpath.read_bytes();im=Image.open(io.BytesIO(imagebytes)).convert('RGB');width,height=im.size;boxes=[]
  for line in lb.decode('utf-8').splitlines():
   if not line.strip():continue
   c,x,y,bw,bh=line.split();x,y,bw,bh=map(float,[x,y,bw,bh]);assert c=='0' and all(math.isfinite(t) for t in [x,y,bw,bh]);boxes.append([(x-bw/2)*width,(y-bh/2)*height,(x+bw/2)*width,(y+bh/2)*height])
  tile=Image.new('RGB',(cw,ch),'#17202e');d=ImageDraw.Draw(tile);d.text((10,0),f'{idx:02d}',font=font(30),fill='white');short=name.removeprefix('frame_').removesuffix('.png').replace('_left',' L').replace('_right',' R');d.text((64,9),short,font=font(19),fill='#d2dfed')
  scale=min(cw/width,250/height);tw,th=round(width*scale),round(height*scale);photo=im.resize((tw,th),Image.Resampling.LANCZOS);pd=ImageDraw.Draw(photo)
  color='#ffad42' if r['label_review_required']=='1' else '#50edab'
  for b in boxes:pd.rectangle(tuple(t*scale for t in b),outline=color,width=2)
  tile.paste(photo,((cw-tw)//2,40+(250-th)//2))
  scene_titles=[title for key,title in [('Small','小目标'),('Occluded','遮挡'),('Blurred','运动模糊'),('No Ball','无球')] if r[key]=='1']
  d.text((10,292),' · '.join(scene_titles),font=font(18),fill='#ffdba6')
  cards.append(tile);records.append(dict(number=idx,filename=name,split=r['split'],image_sha256=digest(imagebytes),label_sha256=digest(lb),flags={k:r[k] for k in ['Small','Occluded','Blurred','No Ball']},label_review_required=r['label_review_required'],scene_review_required=r['scene_review_required'],boxes_xyxy=boxes))
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');out=work/'flat-preview'/f'batch-{a.batch:03d}-group-{a.group:03d}'/stamp;out.mkdir(parents=True,exist_ok=False)
 def render(subset,start,filename):
  cols=5;canvas=Image.new('RGB',(cols*cw,60+math.ceil(len(subset)/cols)*ch),'#0d1420');d=ImageDraw.Draw(canvas);d.text((12,8),f'第{a.batch}批 / 第{a.group}组  ·  {start+1:02d}—{start+len(subset):02d}号  ·  点击原图可放大，按编号指出问题',font=font(25),fill='white')
  for k,tile in enumerate(subset):canvas.paste(tile,((k%cols)*cw,60+(k//cols)*ch))
  canvas.save(out/filename)
 render(cards,0,'all-50.png')
 for start in range(0,len(cards),25):render(cards[start:start+25],start,f'part-{start//25+1}.png')
 (out/'index.json').write_text(json.dumps(dict(batch=a.batch,group=a.group,metadata_sha256=digest(raw),created_at_utc=stamp,records=records),ensure_ascii=False,indent=2)+'\n')
 with (out/'index.csv').open('w',encoding='utf-8-sig',newline='') as f:
  wr=csv.writer(f);wr.writerow(['编号','图片','split','Small','Occluded','Blurred','No Ball']);wr.writerows([q['number'],q['filename'],q['split'],*[q['flags'][k] for k in ['Small','Occluded','Blurred','No Ball']]] for q in records)
 print(json.dumps(dict(output=str(out),images=len(cards),metadata_unchanged=digest((root/'metadata.csv').read_bytes())==digest(raw)),ensure_ascii=False))
if __name__=='__main__':main()
