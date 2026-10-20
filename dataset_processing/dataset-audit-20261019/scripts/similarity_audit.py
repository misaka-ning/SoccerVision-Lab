#!/usr/bin/env python3
"""Cross-split candidate retrieval; distances never automatically prove leakage."""
import csv,hashlib,json,math,time
from collections import Counter,defaultdict
from itertools import combinations
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

cv2.setNumThreads(1)
ROOT=Path(__file__).resolve().parents[1]
rows=json.loads((ROOT/'data/inventory.json').read_text())
prov=json.loads((ROOT/'data/provenance.json').read_text())['records']
gray=np.load(ROOT/'data/gray128x72.npz')['gray']
e=np.load(ROOT/'data/embeddings.npz'); emb=e['features']; emb_index={int(v):i for i,v in enumerate(e['indices'])}
ph=[int(r['phash'],16) for r in rows];dh=[int(r['dhash'],16) for r in rows]
groups={s:[r['index'] for r in rows if r['split']==s] for s in ('train','val','test')}
def current_image(row):
    original=Path(row['image_path'])
    if original.is_file():return original
    assert row['meta']['annotation_status']=='reviewed_excluded'
    isolated=Path('/home/misaka/workspace/datasets/excluded/images')/row['split']/row['filename']
    assert isolated.is_file(), isolated
    return isolated
sources=defaultdict(set)
def add(a,b,why):
    if a==b or rows[a]['split']==rows[b]['split']:return
    sources[tuple(sorted((a,b)))].add(why)
class BK:
    def __init__(self,indices,values):
        self.values=values;self.tree=None
        for i in indices:
            value=values[i]
            if self.tree is None:self.tree=[value,[i],{}];continue
            node=self.tree
            while True:
                d=(value^node[0]).bit_count()
                if not d:node[1].append(i);break
                if d not in node[2]:node[2][d]=[value,[i],{}];break
                node=node[2][d]
    def query(self,value,radius):
        if self.tree is None:return []
        stack=[self.tree];out=[]
        while stack:
            node=stack.pop();d=(value^node[0]).bit_count()
            if d<=radius:out.extend((i,d) for i in node[1])
            stack.extend(n for edge,n in node[2].items() if d-radius<=edge<=d+radius)
        return out

validation=[]
for title,values in [('phash',ph),('dhash',dh)]:
    tree=BK(groups['train'],values)
    for query in groups['val'][::max(1,len(groups['val'])//8)][:8]:
        found=set(tree.query(values[query],16))
        brute={(i,(values[i]^values[query]).bit_count()) for i in groups['train'] if (values[i]^values[query]).bit_count()<=16}
        assert found==brute
        validation.append(dict(hash=title,query=rows[query]['filename'],radius=16,matches=len(found),equals_brute_force=True))
(ROOT/'data/hash-index-validation.json').write_text(json.dumps(dict(success=True,checks=validation),indent=2)+'\n')

thresholds=[0,2,4,6,8,10,12,16]
hash_summary={};cos_summary={};exact=[]
for hash_field in ('image_sha256','pixel_sha256'):
    buckets=defaultdict(list)
    for r in rows:buckets[r[hash_field]].append(r['index'])
    for key,inds in buckets.items():
        if len({rows[i]['split'] for i in inds})>1:
            exact.append(dict(method=hash_field,hash=key,indices=inds))
            for a,b in combinations(inds,2):add(a,b,hash_field)

for s,t in combinations(groups,2):
    key=s+'-'+t
    hash_summary[key]={'all_cross_pairs':len(groups[s])*len(groups[t])}
    for title,values,cut in [('phash',ph,12),('dhash',dh,10)]:
        tree=BK(groups[s],values);dist=Counter();usable=Counter()
        for b in groups[t]:
            for a,d in tree.query(values[b],16):
                dist[d]+=1
                if rows[a]['usable'] and rows[b]['usable']:usable[d]+=1
                if d<=cut:add(a,b,title)
        hash_summary[key][title]={str(x):sum(n for d,n in dist.items() if d<=x) for x in thresholds}
        hash_summary[key][title+'_both_usable']={str(x):sum(n for d,n in usable.items() if d<=x) for x in thresholds}
    a_ids=[i for i in groups[s] if i in emb_index];b_ids=[i for i in groups[t] if i in emb_index]
    aa=emb[[emb_index[i] for i in a_ids]];bb=emb[[emb_index[i] for i in b_ids]]
    all_scores=[];nearest=[];best_for_a=np.full(len(a_ids),-np.inf,dtype=np.float32);best_b=np.zeros(len(a_ids),dtype=int)
    for start in range(0,len(b_ids),32):
        scores=np.clip(bb[start:start+32]@aa.T,-1,1);all_scores.append(scores.reshape(-1))
        for local,score in enumerate(scores):
            b=b_ids[start+local];best=np.argsort(score)[-5:][::-1]
            nearest.append(float(score[best[0]]))
            for j in best:add(a_ids[int(j)],b,'embedding_top5_eval_query')
        maxima=scores.max(axis=0);which=scores.argmax(axis=0);take=maxima>best_for_a
        best_for_a[take]=maxima[take];best_b[take]=which[take]+start
    for j,a in enumerate(a_ids):add(a,b_ids[int(best_b[j])],'embedding_reverse_top1')
    values=np.concatenate(all_scores)
    cos_summary[key]=dict(images_a=len(a_ids),images_b=len(b_ids),all_cross_pairs=len(values),
        all_pair_quantiles={str(q):float(np.quantile(values,q)) for q in (0,.01,.05,.25,.5,.75,.95,.99,1)},
        nearest_eval_quantiles={str(q):float(np.quantile(nearest,q)) for q in (0,.25,.5,.75,.95,1)},
        threshold_pairs={str(q):int((values>=q).sum()) for q in (.90,.95,.97,.98,.99,.995)})
    print(json.dumps(dict(split_pair=key,hash_summary=hash_summary[key],cos_summary=cos_summary[key])),flush=True)

with (ROOT/'data/temporal_pairs.csv').open(encoding='utf-8-sig',newline='') as stream:
    for row in csv.DictReader(stream):add(int(row['index_a']),int(row['index_b']),'confirmed_recording_temporal_nearest')

def ssim(a,b):
    a=a.astype(np.float32);b=b.astype(np.float32)
    ma=cv2.GaussianBlur(a,(11,11),1.5);mb=cv2.GaussianBlur(b,(11,11),1.5)
    va=cv2.GaussianBlur(a*a,(11,11),1.5)-ma*ma
    vb=cv2.GaussianBlur(b*b,(11,11),1.5)-mb*mb
    co=cv2.GaussianBlur(a*b,(11,11),1.5)-ma*mb
    result=((2*ma*mb+6.5025)*(2*co+58.5225))/((ma*ma+mb*mb+6.5025)*(va+vb+58.5225))
    return float(result[5:-5,5:-5].mean())

pairs=[]
for (a,b),why in sorted(sources.items()):
    ra,rb=rows[a],rows[b];pa,pb=prov[ra['filename']],prov[rb['filename']]
    same_recording=bool(pa.get('recording_id') and pa.get('recording_id')==pb.get('recording_id'))
    fa,fb=pa.get('source_frame_idx'),pb.get('source_frame_idx')
    delta=abs(int(fa)-int(fb)) if same_recording and fa is not None and fb is not None else None
    fps=pa.get('fps') if same_recording and pa.get('fps')==pb.get('fps') else None
    cos=float(np.clip(emb[emb_index[a]]@emb[emb_index[b]],-1,1)) if a in emb_index and b in emb_index else None
    small_ssim=ssim(gray[a],gray[b])
    item=dict(index_a=a,index_b=b,image_a=str(current_image(ra)),image_b=str(current_image(rb)),
       original_image_a=ra['image_path'],original_image_b=rb['image_path'],
       filename_a=ra['filename'],filename_b=rb['filename'],split_a=ra['split'],split_b=rb['split'],
       usable_a=ra['usable'],usable_b=rb['usable'],both_usable=ra['usable'] and rb['usable'],
       source_video_a=pa.get('source_video') or '',source_video_b=pb.get('source_video') or '',
       recording_id_a=pa.get('recording_id') or '',recording_id_b=pb.get('recording_id') or '',
       session_a=pa.get('physical_session_id') or '',session_b=pb.get('physical_session_id') or '',
       physical_session_a=pa.get('physical_session_id') or '',physical_session_b=pb.get('physical_session_id') or '',
       frame_a=fa,frame_b=fb,eye_a=pa.get('eye') or '',eye_b=pb.get('eye') or '',
       exact_match=ra['image_sha256']==rb['image_sha256'],pixel_exact_match=ra['pixel_sha256']==rb['pixel_sha256'],
       phash_distance=(ph[a]^ph[b]).bit_count(),dhash_distance=(dh[a]^dh[b]).bit_count(),
       ssim=small_ssim,ssim_128x72=small_ssim,ssim_resolution='128x72',ssim_aligned=None,
       cosine_similarity=cos,same_recording=same_recording,delta_frames=delta,
       delta_seconds=delta/fps if delta is not None and fps else None,
       retrieval_methods=sorted(why),review_status='',assessment_status='candidate_only',
       scene_disagreement=[k for k in ('Small','Occluded','Blurred','No Ball') if ra['meta'][k]!=rb['meta'][k]],
       box_count_a=ra['box_count'],box_count_b=rb['box_count'])
    pairs.append(item)

def risk(r):
    p,d,s,c=r['phash_distance'],r['dhash_distance'],r['ssim'],r['cosine_similarity']
    if r['exact_match'] or r['pixel_exact_match']:return 'critical','跨集合文件或解码像素完全重复'
    if r['same_recording'] and r['delta_frames']==0:return 'critical','同视频同帧跨集合（包括左右目）'
    if r['delta_seconds'] is not None and r['delta_seconds']<=1:return 'high','已确认同录像且相隔不超过1秒；须结合运动和图像复核时序泄漏'
    if p<=4 and d<=6 and ((c is not None and c>=.97) or s>=.82):return 'high','两种感知哈希共同接近，且深度特征或结构相似；SSIM不作为硬性否决，采集事件待核验'
    if c is not None and c>=.985 and s>=.60 and (p<=8 or d<=8):return 'high','深度全局特征及感知哈希共同接近，结构至少部分重合；须人工排除背景相似，不能自动认定泄漏'
    if (p<=10 and d<=12) or (c is not None and c>=.95 and s>=.75):return 'medium','多项视觉相似或背景相近，需区分共同环境与同一采集事件'
    if r['same_recording']:return 'medium','同一录像分到多个集合；时间间隔较大，不自动认定重复'
    return 'low','单项检索召回；可能只是相似背景或不同事件'

# Refine all initial high-risk candidates at a second resolution using source pixels.
cache={}
def larger(i):
    if i not in cache:
        with Image.open(current_image(rows[i])) as im:cache[i]=np.asarray(im.convert('L').resize((256,144),Image.Resampling.BILINEAR))
    return cache[i]
for r in pairs:
    level,_=risk(r)
    if level in ('critical','high'):
        aa,bb=larger(r['index_a']),larger(r['index_b'])
        r['ssim']=ssim(aa,bb);r['ssim_resolution']='256x144'
    r['risk_level'],r['recommended_review_reason']=risk(r)
    r['evidence']='; '.join(r['retrieval_methods'])+f"; pHash={r['phash_distance']}, dHash={r['dhash_distance']}, SSIM={r['ssim']:.4f}"+(f"; same_recording_delta={r['delta_frames']}frames" if r['same_recording'] else '')
    if r['exact_match'] or r['pixel_exact_match']:r['assessment_status']='confirmed_exact_duplicate'
    elif r['same_recording'] and r['delta_frames']==0:r['assessment_status']='confirmed_same_capture_cross_split'
    elif r['delta_seconds'] is not None and r['delta_seconds']<=1:r['assessment_status']='confirmed_temporal_adjacency_not_automatically_visual_duplicate'

rank={'critical':0,'high':1,'medium':2,'low':3}
pairs.sort(key=lambda x:(rank[x['risk_level']],not x['both_usable'],x['delta_frames'] if x['delta_frames'] is not None else 999999,x['phash_distance'],x['dhash_distance'],-x['ssim']))
for n,r in enumerate(pairs):r['pair_id']=f'P{n+1:06d}'
alignment=[]
for r in [x for x in pairs if x['risk_level'] in ('critical','high')][:200]:
    aa,bb=larger(r['index_a']),larger(r['index_b'])
    shift,response=cv2.phaseCorrelate(aa.astype(np.float32),bb.astype(np.float32))
    if response>=.3 and math.hypot(*shift)<=8:
        dx,dy=shift;warped=cv2.warpAffine(bb,np.float32([[1,0,-dx],[0,1,-dy]]),(256,144),borderMode=cv2.BORDER_REFLECT)
        # Crop another 10px to remove the translated border region from comparison.
        r['ssim_aligned']=ssim(aa[10:-10,10:-10],warped[10:-10,10:-10])
        r['alignment_dx'],r['alignment_dy'],r['alignment_phase_response']=dx,dy,response
        alignment.append(r['pair_id'])

cols=['pair_id','image_a','image_b','split_a','split_b','usable_a','usable_b','both_usable','source_video_a','source_video_b','recording_id_a','recording_id_b','session_a','session_b','physical_session_a','physical_session_b','frame_a','frame_b','eye_a','eye_b','exact_match','pixel_exact_match','phash_distance','dhash_distance','ssim','ssim_resolution','ssim_aligned','cosine_similarity','same_recording','delta_frames','delta_seconds','risk_level','assessment_status','evidence','recommended_review_reason','review_status']
with (ROOT/'cross_split_duplicates.csv').open('w',encoding='utf-8-sig',newline='') as stream:
    writer=csv.DictWriter(stream,fieldnames=cols,extrasaction='ignore');writer.writeheader();writer.writerows(pairs)
(ROOT/'data/similarity-pairs.json').write_text(json.dumps(pairs,ensure_ascii=False,indent=2)+'\n')
summary=dict(methods=dict(hash_index='BK-tree Hamming64, exact radius16 retrieval separately for pHash/dHash; candidates p<=12 OR d<=10',
               embedding='L2 normalized pretrained MobileNetV3-small576, exact bounded cross-split inner product; eval top5 + reverse top1',
               ssim='Wang-style Gaussian11 sigma1.5, data_range255, valid border crop, grayscale full-frame resize128x72; initial high-risk refined256x144',
               alignment='Up to first200 high-risk pairs; phase-correlation translation only, response>=.3 and shift<=8px; aligned SSIM diagnostic only',
               source_images_written=False,thresholds_not_groundtruth=True),
             hash_threshold_counts=hash_summary,cosine_distributions=cos_summary,
             risk_policy=dict(critical='file/pixel exact or confirmed same video/frame',
                              high_temporal='confirmed same video and <=1 second, irrespective of visual score',
                              high_visual='(pHash<=4 AND dHash<=6 AND (cosine>=.97 OR SSIM>=.82)) OR (cosine>=.985 AND SSIM>=.60 AND (pHash<=8 OR dHash<=8))',
                              justification='Operational review triage, not universal duplicate thresholds; joint signals only; low SSIM cannot veto camera motion/exposure candidates. No automatic deletion or split assignment.'),
             exact_duplicate_groups=exact,candidate_pairs=len(pairs),risk_counts=dict(Counter(r['risk_level'] for r in pairs)),
             both_usable_risk_counts=dict(Counter(r['risk_level'] for r in pairs if r['both_usable'])),
             alignment_executed_pairs=len(alignment),metrics_missing_reason='cosine blank if either image is excluded; embeddings extracted only for usable8148. alignedSSIM blank outside diagnostic selected/valid shifts.',
             split_pair_counts={},source_inventory_sha256=hashlib.sha256((ROOT/'data/inventory.json').read_bytes()).hexdigest())
for s,t in combinations(groups,2):
    subset=[r for r in pairs if {r['split_a'],r['split_b']}=={s,t}]
    summary['split_pair_counts'][s+'-'+t]=dict(candidates=len(subset),risk=dict(Counter(r['risk_level'] for r in subset)),
        both_usable_risk=dict(Counter(r['risk_level'] for r in subset if r['both_usable'])),
        affected_images_both_usable={split:len({r['index_a'] if r['split_a']==split else r['index_b'] for r in subset if r['both_usable'] and r['risk_level'] in ('critical','high')}) for split in (s,t)})
(ROOT/'data/similarity-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k not in ('hash_threshold_counts','cosine_distributions')},ensure_ascii=False,indent=2),flush=True)
