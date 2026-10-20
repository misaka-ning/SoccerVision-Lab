from common import *
from datetime import datetime,timezone

def main():
 metadata=csvrows(DATA/'metadata.csv');inv=load(AUDIT/'data/inventory.json');prov=load(AUDIT/'data/provenance.json')['records']
 assert len(metadata)==len(inv)==8398
 byname={r['filename']:r for r in inv}
 source_hashes={str(p):sha(p) for p in [DATA/'metadata.csv',DATA/'dataset.yaml',DATA/'SPLIT_POLICY.md',DATA/'excluded/manifest.json',DATA/'excluded/metadata.csv',DATA/'excluded/README.md']}
 (ROOT/'analysis/source-metadata.csv').write_bytes((DATA/'metadata.csv').read_bytes())
 (ROOT/'analysis/source-dataset.yaml').write_bytes((DATA/'dataset.yaml').read_bytes())
 rows=[];counts=defaultdict(Counter)
 for meta in metadata:
  name=meta['图片'];old=byname[name];p=prov[name];ex=meta['annotation_status']=='reviewed_excluded'
  source='legacy' if name.startswith('legacy_') else SOURCE_KEYS[p['recording_id']]
  root=DATA/'excluded' if ex else DATA
  ip=root/'images'/meta['split']/name;lp=root/'labels'/meta['split']/(Path(name).stem+'.txt')
  assert ip.is_file() and lp.is_file() and not ip.is_symlink() and not lp.is_symlink()
  assert meta['scene_review_required']==meta['label_review_required']=='0'
  label=lp.read_bytes();boxes=[list(map(float,line.split())) for line in label.decode('utf-8-sig').splitlines() if line.strip()]
  for b in boxes:assert len(b)==5
  frame=p['source_frame_idx'];fps=p['fps']
  rows.append(dict(index=old['index'],filename=name,source=source,recording_id=p['recording_id'] or 'legacy_recording_unknown',
   session_id='session_legacy_conservative_group' if source=='legacy' else 'session_20261013_'+source,
   session_id_type='pooled_two_sessions_user_recalled' if source=='legacy' else 'physical_session_user_confirmed',
   source_split=meta['split'],excluded=ex,frame=frame,seconds=frame/fps if frame is not None and fps else None,fps=fps,eye=p['eye'] or 'unknown',
   source_image=str(ip),source_label=str(lp),width=old['width'],height=old['height'],boxes=boxes,
   flags={k:int(meta[k]) for k in FLAGS},annotation_status=meta['annotation_status'],
   image_sha256=old['image_sha256'],pixel_sha256=old['pixel_sha256'],label_sha256=hashlib.sha256(label).hexdigest(),
   phash=old['phash'],dhash=old['dhash'],stat_before={'size':ip.stat().st_size,'mtime_ns':ip.stat().st_mtime_ns,'inode':ip.stat().st_ino}))
  counts[source]['all']+=1;counts[source]['excluded' if ex else 'usable']+=1
 active=[r for r in rows if not r['excluded']]
 assert len(active)==8148 and sum(r['excluded'] for r in rows)==250
 assert Counter(r['source_split'] for r in active)=={'train':6925,'val':1223}
 assert {k:v['usable'] for k,v in counts.items()}=={'104748':1154,'legacy':713,'181326':69,'181531':6212}
 save(ROOT/'analysis/source_inventory.json',rows)
 oldpairs=load(AUDIT/'data/similarity-pairs.json');lookup={r['filename']:r for r in rows}
 high=[p for p in oldpairs if p['risk_level']=='high']
 reused=dict(cached_inventory=str(AUDIT/'data/inventory.json'),pixel_hashes_reused_condition='Each source file SHA must match cached raw-file SHA at final verification; then cached decoded RGB pixel hash is still valid.',
  embedding=str(AUDIT/'data/embeddings.npz'),embedding_model=load(AUDIT/'data/embedding-model.json'),
  gray_cache=str(AUDIT/'data/gray128x72.npz'),old_candidate_count=len(oldpairs),old_high_count=len(high),
  old_high_now_cross_formal_source_split=sum(lookup[p['filename_a']]['source_split']!=lookup[p['filename_b']]['source_split'] for p in high),
  old_temporal_candidate_rows=len(csvrows(AUDIT/'data/temporal_pairs.csv')),
  source_hashes=source_hashes,counts={k:dict(v) for k,v in counts.items()},seed=SEED,prepared_at_utc=datetime.now(timezone.utc).isoformat())
 save(ROOT/'analysis/reused_evidence.json',reused)
 facts=dict(authority='User message in this task,2026-10-19; supersedes uncertainty/speculation in previous audit.',
  environment='No football-pitch environment in any current source, confirmed by user.',
  recordings=[dict(recording_id=k,session_id='session_20261013_'+v,physical_session_independent_of_other_two=True,evidence='user_confirmed') for k,v in SOURCE_KEYS.items()],
  legacy=dict(physical_sessions_user_recalled=2,analysis_group_count=1,session_id='session_legacy_conservative_group',trace_individual_sessions=False),
  evaluation_kind='same_session_segment_holdout',test_physical_session_count=1,
  val_locked=True,all_weights_prior_exposure_status='unknown unless complete training-image provenance becomes available',no_training_or_prediction_score_selection=True)
 save(ROOT/'SOURCE_FACTS.json',facts)
 timeline=representatives([r for r in active if r['source']=='181531'])
 arr=np.load(AUDIT/'data/embeddings.npz');feature_by_index={int(i):f for i,f in zip(arr['indices'],arr['features'])}
 summaries=[]
 for start in range(0,1620,20):
  rr=[r for r in timeline if start<=r['seconds']<start+20]
  if not rr:continue
  ff=np.stack([feature_by_index[r['index']] for r in rr]);delta=1-(ff[1:]*ff[:-1]).sum(1)
  summaries.append(dict(start_seconds=start,end_seconds=start+20,moments=len(rr),mean_motion=float(delta.mean()) if len(delta) else 0,
   p90_motion=float(np.quantile(delta,.9)) if len(delta) else 0,**{k:sum(r['flags'][k] for r in rr) for k in FLAGS},
   ordinary=sum(not any(r['flags'][k] for k in FLAGS) for r in rr)))
 writecsv(ROOT/'analysis/timeline_20s.csv',summaries)
 selected=[]
 for t in range(0,1620,10):
  r=min(timeline,key=lambda r:abs(r['seconds']-t))
  if not selected or r['frame']!=selected[-1]['frame']:selected.append(r)
 pages=[]
 for j in range(0,len(selected),20):
  pages.append(contact(selected[j:j+20],ROOT/f'evidence/overview-{j//20:02}.jpg',f'181531 timeline / page{j//20+1} / every10s overview',cols=5))
 save(ROOT/'analysis/overview_pages.json',pages)
 print(json.dumps(dict(active=len(active),video_moments=len(timeline),overview_pages=len(pages),counts=reused['counts']),ensure_ascii=False))

if __name__=='__main__':main()
