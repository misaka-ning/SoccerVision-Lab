from common import *
from screen_pairs import pair_page
pairs=load(ROOT/'analysis/new_similarity_pairs.json');review=load(ROOT/'analysis/pairs_to_visually_review.json');seen={p['pair_id'] for p in review}
lookup={r['index']:r for r in load(ROOT/'analysis/source_inventory.json')}
for field,reverse in [('cosine',True),('ssim',True),('phash',False),('dhash',False)]:
 test_seen=set()
 for p in sorted(pairs,key=lambda p:p[field],reverse=reverse):
  if p['test_image'] in test_seen:continue
  test_seen.add(p['test_image'])
  if p['pair_id'] not in seen:
   seen.add(p['pair_id']);p['selected_review_reason']='metric_extreme_'+field
   path=ROOT/'evidence/pairs'/f'{p["pair_id"]}.jpg';pair_page(p,lookup,path)
   p['evidence_path']=str(path.relative_to(ROOT));p['evidence_sha256']=sha(path);review.append(p)
  if len(test_seen)>=2:break
save(ROOT/'analysis/pairs_to_visually_review.json',review)
print(json.dumps(dict(review_pairs=len(review),new_ids=[p['pair_id'] for p in review[52:]])))
