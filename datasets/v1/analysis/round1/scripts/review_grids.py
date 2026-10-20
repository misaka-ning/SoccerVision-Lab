from common import *
rows=load(ROOT/'analysis/source_inventory.json');lookup={r['index']:r for r in rows}
pairs=load(ROOT/'analysis/pairs_to_visually_review.json');pages=[]
for start in range(0,len(pairs),4):
 pp=pairs[start:start+4];w=672;h=270;canvas=Image.new('RGB',(w*2,h*2),'#f5f6f8');d=ImageDraw.Draw(canvas)
 for n,p in enumerate(pp):
  x=n%2*w;y=n//2*h;a=lookup[p['test_index']];b=lookup[p['other_index']]
  d.text((x+5,y+3),f'{p["pair_id"]} {p["segment_id"]} {stamp(a["seconds"])} Test | '+p['other_role']+' '+(stamp(b['seconds']) if b['seconds'] is not None else b['source']),fill='#152333',font=font(14))
  canvas.paste(tile(a,336,188),(x,y+25));canvas.paste(tile(b,336,188),(x+336,y+25))
  d.text((x+5,y+217),f'cos {p["cosine"]:.4f} / SSIM {p["ssim"]:.3f} / p{p["phash"]} d{p["dhash"]} / {p["risk"]}',fill='#152333',font=font(14))
  d.text((x+5,y+242),' | '.join(' '.join(k for k in FLAGS if r['flags'][k]) or 'ordinary' for r in [a,b]),fill='#925019',font=font(12))
 path=ROOT/f'evidence/pairs/review-grid-{start//4:02}.jpg';canvas.save(path,quality=90)
 pages.append(dict(path=str(path.relative_to(ROOT)),pair_ids=[p['pair_id'] for p in pp],sha256=sha(path)))
save(ROOT/'analysis/risk_review_grids.json',pages)
writecsv(ROOT/'analysis/pairs_review_table.csv',pairs,['pair_id','segment_id','test_image','other_image','other_role','test_seconds','other_seconds','cosine','phash','dhash','ssim','risk'])
print(json.dumps(dict(grids=len(pages),pairs=len(pairs)),ensure_ascii=False))
