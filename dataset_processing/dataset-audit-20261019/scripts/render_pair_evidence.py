"""Render reproducible comparison pages in the audit directory only."""
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]
pairs=json.loads((ROOT/'data/similarity-pairs.json').read_text())
rows=json.loads((ROOT/'data/inventory.json').read_text())
folder=ROOT/'review/pair-pages';folder.mkdir(parents=True,exist_ok=True)
font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',12)
chosen=[]
high=[r for r in pairs if r['risk_level']=='high']
chosen.extend(high)
# Include actual Val/Test comparators and the strongest medium semantic matches.
for s,t in [('val','test'),('train','val'),('train','test')]:
    candidates=[r for r in pairs if {r['split_a'],r['split_b']}=={s,t} and r['risk_level']=='medium']
    for order in (lambda r:-r['ssim'],lambda r:-(r['cosine_similarity'] or 0)):
        chosen.extend(sorted(candidates,key=order)[:3])
seen=set();selected=[]
for r in chosen:
    if r['pair_id'] in seen:continue
    seen.add(r['pair_id']);selected.append(r)
    tiles=[]
    for eye in ('a','b'):
        src=rows[r['index_'+eye]]
        with Image.open(r['image_'+eye]) as im:
            im=im.convert('RGB');w,h=im.size
            scale=672/w
            if w!=672:im=im.resize((672,round(h*scale)),Image.Resampling.BILINEAR)
        dr=ImageDraw.Draw(im)
        for box in src['boxes']:
            x1,y1,x2,y2=box['xyxy']
            # inventory xyxy is normalized, including recorded invalid archived boxes.
            dr.rectangle([x1*im.width,y1*im.height,x2*im.width,y2*im.height],outline='#ff3838',width=1)
        header=Image.new('RGB',(672,44),'#202020');d=ImageDraw.Draw(header)
        d.text((4,2),f"{r['pair_id']} {r['split_'+eye]} {src['filename']} {w}x{h}",font=font,fill='white')
        selected_flags=[k for k in ('Small','Occluded','Blurred','No Ball') if src['meta'][k]=='1']
        d.text((4,20),f"frame={r['frame_'+eye]} eye={r['eye_'+eye]} boxes={src['box_count']} "+', '.join(selected_flags),font=font,fill='#dddddd')
        tile=Image.new('RGB',(672,im.height+44),'#202020');tile.paste(header);tile.paste(im,(0,44));tiles.append(tile)
    footer=Image.new('RGB',(672,55),'#202020');d=ImageDraw.Draw(footer)
    cosine=r['cosine_similarity'];aligned=r['ssim_aligned']
    d.text((4,3),f"{r['risk_level']} pHash={r['phash_distance']} dHash={r['dhash_distance']} SSIM={r['ssim']:.4f}({r['ssim_resolution']}) cosine={cosine if cosine is not None else 'NA'}",font=font,fill='white')
    d.text((4,21),f"delta_frames={r['delta_frames']} delta_seconds={r['delta_seconds']} alignedSSIM={aligned}",font=font,fill='white')
    canvas=Image.new('RGB',(672,sum(t.height for t in tiles)+55),'#202020');y=0
    for tile in tiles+[footer]:canvas.paste(tile,(0,y));y+=tile.height
    path=folder/(r['pair_id']+'.png');canvas.save(path)
    r['evidence_page']=str(path)
(ROOT/'data/rendered-pair-evidence.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(pages=len(selected),high_pages=len(high),directory=str(folder))))
