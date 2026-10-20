from common import *
import time

class BK:
 def __init__(self,rows,key):
  self.tree=None
  for r in rows:
   v=int(r[key],16);i=r['index']
   if self.tree is None:self.tree=[v,[i],{}];continue
   node=self.tree
   while True:
    d=(v^node[0]).bit_count()
    if not d:node[1].append(i);break
    if d not in node[2]:node[2][d]=[v,[i],{}];break
    node=node[2][d]
 def query(self,v,rad):
  out=[];stack=[self.tree] if self.tree else []
  while stack:
   node=stack.pop();d=(v^node[0]).bit_count()
   if d<=rad:out.extend((i,d) for i in node[1])
   stack.extend(n for edge,n in node[2].items() if d-rad<=edge<=d+rad)
  return out

def role(r,segments):
 if r['source_split']=='val':return 'val'
 if r['source']=='181531':
  for s in segments:
   if s['buffer_start_seconds']<=r['seconds']<=s['buffer_end_seconds']:
    return 'heldout_unused' if s['start_seconds']<=r['seconds']<=s['end_seconds'] else 'buffer'
 return 'train'

def pair_page(p,lookup,path):
 a,b=lookup[p['test_index']],lookup[p['other_index']]
 w=672;h=376;canvas=Image.new('RGB',(w*2,h+144),'#f2f4f7');d=ImageDraw.Draw(canvas)
 d.text((10,8),f'{p["pair_id"]} / {p["segment_id"]} {stamp(a["seconds"])} vs {p["other_role"]} '+(stamp(b['seconds']) if b['seconds'] is not None else b['filename']),fill='#101d2a',font=font(18))
 canvas.paste(tile(a,w,h),(0,38));canvas.paste(tile(b,w,h),(w,38))
 for x,r in [(0,a),(w,b)]:
  d.text((x+8,h+43),r['filename'],fill='#101d2a',font=font(13))
  d.text((x+8,h+63),' '.join(k for k in FLAGS if r['flags'][k]) or 'ordinary clear ball',fill='#8d4612',font=font(14))
 d.text((10,h+89),f'cos={p["cosine"]:.5f} pHash={p["phash"]} dHash={p["dhash"]} SSIM128={p["ssim"]:.4f} / {p["risk"]} / same recording={p["same_recording"]}',fill='#14202e',font=font(15))
 d.text((10,h+113),'Similarity is review evidence; background agreement is not an event identity decision.',fill='#4a5968',font=font(13))
 canvas.save(path,quality=88)

def main():
 started=time.monotonic();rows=[r for r in load(ROOT/'analysis/source_inventory.json') if not r['excluded']]
 segments=load(ROOT/'analysis/segments.json');queries=load(ROOT/'analysis/initial_test_representatives.json');lookup={r['index']:r for r in rows}
 segment_by_name={r['filename']:r['segment_id'] for r in queries}
 feat=np.load(AUDIT/'data/embeddings.npz');fv={int(i):v for i,v in zip(feat['indices'],feat['features'])}
 gray=np.load(AUDIT/'data/gray128x72.npz')['gray']
 others={k:[r for r in rows if role(r,segments)==k] for k in ['train','val']}
 sources=defaultdict(set);nearest=[];hash_validations=[]
 for target,rr in others.items():
  indices=np.array([r['index'] for r in rr]);ff=np.stack([fv[int(i)] for i in indices])
  for st in range(0,len(queries),32):
   qq=queries[st:st+32];score=np.stack([fv[r['index']] for r in qq])@ff.T
   for q,values in zip(qq,score):
    top=np.argsort(values)[-8:][::-1]
    nearest.append(dict(query=q['filename'],target=target,maximum_cosine=float(values[top[0]])))
    for j in top:sources[(q['index'],int(indices[j]))].add('embedding_top8_'+target)
  for hashkey,cut in [('phash',12),('dhash',10)]:
   tree=BK(rr,hashkey)
   for qi,q in enumerate(queries):
    found=tree.query(int(q[hashkey],16),cut)
    for i,distance in found:sources[(q['index'],i)].add(hashkey+'_radius'+str(cut))
    if qi in [0,len(queries)//2,len(queries)-1]:
     brute={(r['index'],(int(r[hashkey],16)^int(q[hashkey],16)).bit_count()) for r in rr if (int(r[hashkey],16)^int(q[hashkey],16)).bit_count()<=cut}
     assert set(found)==brute
     hash_validations.append(dict(target=target,hash=hashkey,query=q['filename'],equal_to_brute_force=True,candidates=len(found)))
  print(json.dumps(dict(target=target,images=len(rr),candidate_union=len(sources))),flush=True)
 pairs=[]
 for n,((ai,bi),methods) in enumerate(sorted(sources.items())):
  a,b=lookup[ai],lookup[bi];c=float(fv[ai]@fv[bi]);s=ssim(gray[ai],gray[bi]);pd=(int(a['phash'],16)^int(b['phash'],16)).bit_count();dd=(int(a['dhash'],16)^int(b['dhash'],16)).bit_count()
  same=a['recording_id']==b['recording_id'];delta=abs(a['seconds']-b['seconds']) if same else None
  exact=a['image_sha256']==b['image_sha256'];pixel=a['pixel_sha256']==b['pixel_sha256']
  high=(c>=.985 and (s>=.77 or (pd<=8 and dd<=10)) and pd<=12 and dd<=14) or (c>=.97 and s>=.87 and pd<=10 and dd<=10) or (pd<=4 and dd<=6 and s>=.80)
  risk='critical' if exact or pixel else 'high' if high or (delta is not None and delta<=5) else 'medium' if c>=.95 or (pd<=10 and dd<=10) else 'low'
  value=dict(test_index=ai,other_index=bi,test_image=a['filename'],other_image=b['filename'],segment_id=segment_by_name[a['filename']],
   other_role=role(b,segments),other_source=b['source'],test_seconds=a['seconds'],other_seconds=b['seconds'],
   test_frame=a['frame'],other_frame=b['frame'],same_recording=same,same_session=a['session_id']==b['session_id'],
   different_session_user_confirmed=a['session_id']!=b['session_id'] and b['source']!='legacy',time_gap_seconds=delta,
   cosine=c,phash=pd,dhash=dd,ssim=s,ssim_resolution='128x72',exact_match=exact,pixel_exact_match=pixel,
   risk=risk,retrieval_methods=sorted(methods),review_status='',assistant_observation='',event_identity_confirmed=False)
  value['priority_score']=c*.45+s*.35+(1-(pd+dd)/128)*.20
  pairs.append(value)
  if n%5000==0:print(json.dumps(dict(metric_pairs=n,total=len(sources))),flush=True)
 rank={'critical':0,'high':1,'medium':2,'low':3}
 pairs.sort(key=lambda p:(rank[p['risk']],-p['priority_score']))
 for i,p in enumerate(pairs,1):p['pair_id']=f'N{i:05d}'
 groups=defaultdict(list)
 for p in pairs:
  bucket=int(p['other_seconds']//15) if p['same_recording'] else p['other_source']
  groups[(p['segment_id'],p['other_role'],str(bucket))].append(p)
 review=[];seen=set()
 def take(p,why):
  if p['pair_id'] not in seen:
   seen.add(p['pair_id']);p['selected_review_reason']=why;review.append(p)
 for p in pairs[:18]:take(p,'highest_joint_priority')
 for s in segments:
  for target in ['train','val']:
   for p in [p for p in pairs if p['segment_id']==s['segment_id'] and p['other_role']==target][:2]:take(p,'segment_and_target_top2')
 for key,rr in sorted(groups.items(),key=lambda kv:(rank[kv[1][0]['risk']],-kv[1][0]['priority_score'])):
  if len(review)>=60:break
  if rr[0]['risk'] in ['critical','high']:take(rr[0],'additional_high_risk_temporal_group')
 ev=ROOT/'evidence/pairs';ev.mkdir(exist_ok=True)
 for p in review:
  path=ev/(p['pair_id']+'.jpg');pair_page(p,lookup,path);p['evidence_path']=str(path.relative_to(ROOT));p['evidence_sha256']=sha(path)
 save(ROOT/'analysis/new_similarity_pairs.json',pairs);save(ROOT/'analysis/pairs_to_visually_review.json',review)
 summary=dict(candidate_pairs=len(pairs),risk_counts=dict(Counter(p['risk'] for p in pairs)),
  high_unique_test_images=len({p['test_image'] for p in pairs if p['risk']=='high'}),queries=len(queries),
  high_by_segment=dict(Counter(p['segment_id'] for p in pairs if p['risk']=='high')),
  reviewed_pages_pending_actual_open=len(review),maxima=nearest,hash_index_checks=hash_validations,
  method='Reused normalized MobileNetV3-small576; bounded exact top8 per candidate and formal target split; BK exact p<=12/d<=10; union SSIM128x72. Thresholds prioritize review and are not event truth.',
  excluded_from_opponents='All held-out cores and adaptive buffers; Val fixed.',elapsed_seconds=time.monotonic()-started)
 save(ROOT/'analysis/new_similarity_summary.json',summary)
 print(json.dumps({k:v for k,v in summary.items() if k not in ['maxima','hash_index_checks']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
