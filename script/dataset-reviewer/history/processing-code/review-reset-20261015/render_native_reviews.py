#!/usr/bin/env python3
import json, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE=Path(__file__).resolve().parent
FONT=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',14)
def render(folder,records):
    (folder/'full').mkdir(parents=True,exist_ok=True);(folder/'roi').mkdir(exist_ok=True)
    (folder/'inventory.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
    full=[];units=[]
    for start in range(0,len(records),6):
        out=Image.new('RGB',(1344,1212),'#202020');draw=ImageDraw.Draw(out)
        for off,r in enumerate(records[start:start+6]):
            x=(off%2)*672;y=(off//2)*404
            draw.text((x+3,y+3),f"n{start+off} i{r['index']} {r['filename']} boxes={len(r['boxes'])}",font=FONT,fill='white')
            im=Image.open(r['image_path']).convert('RGB');assert im.size==(672,376)
            overlay=im.copy();d=ImageDraw.Draw(overlay)
            for b in r['boxes']:d.rectangle(b['xyxy'],outline='#ff3030',width=1)
            out.paste(overlay,(x,y+26))
        page=folder/'full'/f'page-{start//6:02d}.png';out.save(page)
        full.append({'path':str(page),'locals':list(range(start,min(start+6,len(records))))})
    for n,r in enumerate(records):
        for b in r['boxes']:
            x1,y1,x2,y2=b['xyxy'];pad=max(16,.2*max(x2-x1,y2-y1))
            crop=[max(0,math.floor(x1-pad)),max(0,math.floor(y1-pad)),min(r['width'],math.ceil(x2+pad)),min(r['height'],math.ceil(y2+pad))]
            units.append({'local':n,'box_index':b['box_index'],'crop':crop,'xyxy':b['xyxy'],'filename':r['filename']})
    for start in range(0,len(units),8):
        out=Image.new('RGB',(1120,1040),'#202020');draw=ImageDraw.Draw(out)
        for off,u in enumerate(units[start:start+8]):
            r=records[u['local']];x=(off%2)*560;y=(off//2)*260
            draw.text((x+3,y+1),f"n{u['local']} b{u['box_index']} {u['filename']}",font=FONT,fill='white')
            draw.text((x+3,y+18),'xyxy '+','.join(f'{v:.2f}' for v in u['xyxy']),font=FONT,fill='white')
            im=Image.open(r['image_path']).convert('RGB').crop(u['crop'])
            scale=min(270/im.width,218/im.height)
            view=im.resize((max(1,round(im.width*scale)),max(1,round(im.height*scale))),Image.Resampling.NEAREST)
            out.paste(view,(x+2,y+39));boxed=view.copy();bd=ImageDraw.Draw(boxed)
            x1,y1,x2,y2=u['xyxy'];cx,cy,_,_=u['crop']
            bd.rectangle(((x1-cx)*scale,(y1-cy)*scale,(x2-cx)*scale,(y2-cy)*scale),outline='#ff3030',width=1)
            out.paste(boxed,(x+282,y+39));u['page']=str(folder/'roi'/f'page-{start//8:02d}.png')
        out.save(folder/'roi'/f'page-{start//8:02d}.png')
    (folder/'manifest.json').write_text(json.dumps({'full':full,'roi':units},ensure_ascii=False,indent=2)+'\n')
    return {'images':len(records),'full_pages':len(full),'boxes':len(units),'roi_pages':math.ceil(len(units)/8)}

if __name__=='__main__':
    records=json.loads((HERE/'batches/batch-001-inventory.json').read_text())
    result={}
    for g in range(4):
        folder=HERE/'batch-001'/f'group-{g+1}';result[str(g+1)]=render(folder,records[g*250:(g+1)*250])
    (HERE/'batch-001/rendered.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
