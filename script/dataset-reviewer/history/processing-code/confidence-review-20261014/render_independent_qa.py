#!/usr/bin/env python3
"""Render an independent full-frame plus ball-outline audit sample."""
import argparse, json, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONT = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 14)

def render(records, target, prefix='sample'):
    target.mkdir(parents=True, exist_ok=True)
    manifest = []
    for start in range(0, len(records), 6):
        out = Image.new('RGB', (1920, 1260), '#222222')
        draw = ImageDraw.Draw(out)
        for offset, entry in enumerate(records[start:start+6]):
            b = entry['record']
            im = Image.open(b['image_path']).convert('RGB')
            annotated = im.copy()
            ad = ImageDraw.Draw(annotated)
            for box in b['boxes']:
                ad.rectangle(box['xyxy'], outline='#ff3030', width=1)
            annotated.thumbnail((672, 376))
            x, y = (offset % 2)*960, (offset // 2)*420
            draw.text((x+5, y+4), f"g{entry.get('group','?')} n{entry.get('local','?')} {b['filename']}", font=FONT, fill='white')
            draw.text((x+5, y+24), entry.get('caption','')[:112], font=FONT, fill='#dddddd')
            out.paste(annotated, (x+4, y+44))
            for bi, box in enumerate(b['boxes'][:2]):
                x1,y1,x2,y2 = box['xyxy']
                pad = max(12, 0.18*max(x2-x1,y2-y1))
                crop = (max(0,math.floor(x1-pad)),max(0,math.floor(y1-pad)),min(im.width,math.ceil(x2+pad)),min(im.height,math.ceil(y2+pad)))
                roi = im.crop(crop)
                rd = ImageDraw.Draw(roi)
                rd.rectangle((x1-crop[0],y1-crop[1],x2-crop[0],y2-crop[1]), outline='#ff3030', width=1)
                area = (278, 176) if len(b['boxes']) > 1 else (278, 332)
                scale = min(area[0]/roi.width,area[1]/roi.height)
                roi = roi.resize((max(1,round(roi.width*scale)),max(1,round(roi.height*scale))),Image.Resampling.NEAREST)
                out.paste(roi,(x+680,y+58+bi*176))
            if not b['boxes']:
                edge = im.crop((0,max(0,im.height-100),im.width,im.height))
                edge.thumbnail((278,100))
                out.paste(edge,(x+680,y+58))
                draw.text((x+683,y+162),'empty label: inspect all native frame edges',font=FONT,fill='white')
        page = target/f'{prefix}-{start//6:02d}.png'
        out.save(page)
        manifest.append({'page':str(page),'records':[{'filename':r['record']['filename'],'group':r.get('group'),'local':r.get('local')} for r in records[start:start+6]]})
    (target/f'{prefix}-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    return manifest

def main():
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--prefix',default='sample');a=p.parse_args()
    print(json.dumps(render(json.loads(a.input.read_text()),HERE/'independent-qa',a.prefix),ensure_ascii=False))

if __name__=='__main__':main()
