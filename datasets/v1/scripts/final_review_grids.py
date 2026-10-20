from common import *
lookup={r['index']:r for r in load(ROOT/'analysis/source_inventory.json')}
pairs=load(ROOT/'analysis/final_pairs_to_visually_review.json')
all_old=load(ROOT/'analysis/pair_visual_observations_round1.json')+load(ROOT/'analysis/pair_visual_observations_round2.json')
old={(p['test_image'],p['other_image']):p for p in all_old}
todo=[];reused=[]
for p in pairs:
 key=p['test_image'],p['other_image']
 if key in old and old[key]['actual_seen']:
  reused.append(dict(final_pair_id=p['pair_id'],original_pair_id=old[key]['pair_id'],test_image=key[0],other_image=key[1],
   observation=old[key]['assistant_observation'],assessment=old[key]['assessment'],original_evidence_sha256=old[key]['evidence_sha256'],
   reused_by='Exact same source image/label identities; pair metadata/rank changes do not require reinterpreting different photographs.'))
 else:todo.append(p)
pages=[]
for start in range(0,len(todo),4):
 pp=todo[start:start+4];w=672;h=270;canvas=Image.new('RGB',(w*2,h*2),'#f5f6f8');d=ImageDraw.Draw(canvas)
 for n,p in enumerate(pp):
  x=n%2*w;y=n//2*h;a=lookup[p['test_index']];b=lookup[p['other_index']]
  d.text((x+5,y+3),f'{p["pair_id"]} {p["segment_id"]} {stamp(a["seconds"])} Test | '+p['other_role']+' '+(stamp(b['seconds']) if b['seconds'] is not None else b['source']),fill='#152333',font=font(14))
  canvas.paste(tile(a,336,188),(x,y+25));canvas.paste(tile(b,336,188),(x+336,y+25))
  d.text((x+5,y+217),f'cos {p["cosine"]:.4f} / SSIM {p["ssim"]:.3f} / p{p["phash"]} d{p["dhash"]} / {p["risk"]}',fill='#152333',font=font(14))
  d.text((x+5,y+242),' | '.join(' '.join(k for k in FLAGS if r['flags'][k]) or 'ordinary' for r in [a,b]),fill='#925019',font=font(12))
 prefix=pairs[0]['pair_id'][0]
 path=ROOT/f'evidence/pairs/{prefix}-final-todo-grid-{start//4:02}.jpg';canvas.save(path,quality=90)
 pages.append(dict(path=str(path.relative_to(ROOT)),pair_ids=[p['pair_id'] for p in pp],sha256=sha(path)))
save(ROOT/'analysis/final_pair_reviews_reused.json',reused);save(ROOT/'analysis/final_pair_review_todo.json',todo);save(ROOT/'analysis/final_pair_todo_grids.json',pages)
print(json.dumps(dict(total=len(pairs),reused=len(reused),todo=len(todo),grids=len(pages),new_pairs=[(p['pair_id'],p['segment_id'],p['test_seconds'],p['other_seconds']) for p in todo]),ensure_ascii=False))
