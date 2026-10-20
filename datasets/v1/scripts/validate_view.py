from common import *
import contextlib,importlib.metadata
from datetime import datetime,timezone

def main():
 manifest=load(ROOT/'manifest.json');records=manifest['records'];byname={r['filename']:r for r in records}
 assert len(records)==len(byname)==8148
 roles=['train','val','test','buffer','heldout_unused'];sets={k:{r['filename'] for r in records if r['usage']==k} for k in roles}
 for i,a in enumerate(roles):
  for b in roles[i+1:]:assert not sets[a]&sets[b]
 assert set.union(*sets.values())==set(byname)
 source=load(ROOT/'analysis/source_inventory.json');excluded={r['filename'] for r in source if r['excluded']}
 assert len(excluded)==250 and not excluded&set(byname)
 assert sets['val']=={r['filename'] for r in source if not r['excluded'] and r['source_split']=='val'}
 assert {r['filename'] for r in records if r['source']=='legacy'}<=sets['train']
 formal={'train','val','test'};side=lambda usage:usage if usage in ['train','val'] else 'withheld'
 frame_sides=defaultdict(set);stats={};source_hashes=load(ROOT/'analysis/reused_evidence.json')['source_hashes']
 blocks=load(ROOT/'analysis/heldout_blocks.json')
 for r in records:
  if r['source_frame_idx'] is not None:frame_sides[r['frame_unit_id']].add(side(r['usage']))
  if r['source']=='181531' and r['usage']=='train':
   assert not any(b['start_seconds']<=r['source_seconds']<=b['end_seconds'] for b in blocks)
  assert sha(r['image'])==r['image_sha256'] and sha(r['label'])==r['label_sha256']
  assert Path(r['image']).stat().st_ino!=Path(r['original_image']).stat().st_ino
 assert all(len(v)==1 for v in frame_sides.values())
 tests=[r for r in records if r['usage']=='test']
 assert len(tests)==len({r['frame_unit_id'] for r in tests})==464
 assert len({r['session_id'] for r in tests})==1
 for r in tests:
  assert r['source']=='181531' and not r['review_group']
 for k in roles:
  rr=[r for r in records if r['usage']==k]
  listed=(ROOT/'lists'/f'{k}.txt').read_text().splitlines()
  assert len(listed)==len(set(listed))==len(rr) and set(listed)=={r['image'] for r in rr}
  stats[k]=dict(images=len(rr),positive_images=sum(r['box_count']>0 for r in rr),negative_images=sum(r['box_count']==0 for r in rr),
   boxes=sum(r['box_count'] for r in rr),source_counts=dict(Counter(r['source'] for r in rr)),
   source_moments_known=len({r['frame_unit_id'] for r in rr if r['source_frame_idx'] is not None}),
   legacy_images_without_frame_identity=sum(r['source_frame_idx'] is None for r in rr),
   segments=len({r['segment_id'] for r in rr}),session_ids=sorted({r['session_id'] for r in rr}),
   scenes={f:dict(images=sum(r[f] for r in rr),positive_images=sum(r[f] and r['box_count']>0 for r in rr),negative_images=sum(r[f] and r['box_count']==0 for r in rr)) for f in FLAGS},
   ordinary_clear_positive=sum(r['box_count']>0 and not any(r[f] for f in FLAGS) for r in rr),
   multiball_images=sum(r['box_count']>1 for r in rr),joint_flags=dict(Counter(''.join(str(r[f]) for f in FLAGS) for r in rr)))
 # Hash grouping uses decoded pixel hashes only after raw-file byte equality above.
 duplicate_groups={}
 for key in ['image_sha256','pixel_sha256']:
  buckets=defaultdict(list)
  for r in records:
   if r['usage'] in formal:buckets[r[key]].append(r)
  cross=[[(r['filename'],r['usage']) for r in rr] for rr in buckets.values() if len({r['usage'] for r in rr})>1]
  assert not cross;duplicate_groups[key]=cross
 old=load(AUDIT/'data/similarity-pairs.json');high=[r for r in old if r['risk_level']=='high']
 for p in high:
  a,b=byname.get(p['filename_a']),byname.get(p['filename_b'])
  if a and b:assert side(a['usage'])==side(b['usage'])
 # Every protected source/copy, including the original250 exclusions, remains byte-identical.
 for r in source:
  assert sha(r['source_image'])==r['image_sha256'];assert sha(r['source_label'])==r['label_sha256']
 for path,expected in source_hashes.items():assert sha(path)==expected
 assert not list(DATA.rglob('*.cache')),'Unexpected source cache'
 # Verify data YAML resolves to our lists, then construct the actual dataset and a real batch.
 import yaml
 data=yaml.safe_load((ROOT/'dataset.yaml').read_text());assert data['path']==str(ROOT) and data['names']=={0:'football'}
 for k in formal:assert data[k]=='lists/'+k+'.txt'
 os.environ['YOLO_CONFIG_DIR']=str(ROOT/'runtime/ultralytics-config');os.environ['MPLCONFIGDIR']=str(ROOT/'runtime/matplotlib-config')
 for p in [ROOT/'runtime/ultralytics-config/Ultralytics',ROOT/'runtime/matplotlib-config']:p.mkdir(parents=True,exist_ok=True)
 import torch
 torch.set_num_threads(1);torch.set_num_interop_threads(1)
 import ultralytics.data.dataset as dm
 from ultralytics.cfg import get_cfg
 from ultralytics.utils import USER_CONFIG_DIR
 assert Path(USER_CONFIG_DIR).is_relative_to(ROOT/'runtime')
 dm.NUM_THREADS=1
 class ObservedDataset(dm.YOLODataset):
  def _load_or_scan_cache(self,path,cache_hash):
   cache,exists=super()._load_or_scan_cache(path,cache_hash)
   self.observed_cache=dict(path=str(path),loaded_existing=exists,results=list(map(int,cache['results'])),hash=cache['hash'])
   return cache,exists
 loader_results={}
 for split in ['train','val','test']:
  cache_path=ROOT/'labels'/f'{split}.cache';fresh_before=not cache_path.exists()
  kwargs=dict(img_path=str(ROOT/data[split]),data=data,task='detect',imgsz=640,batch_size=2,cache=False,augment=False,rect=False,hyp=get_cfg())
  with (ROOT/'runtime'/f'{split}-dataset-loader.log').open('w') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
   ds=ObservedDataset(**kwargs);initial=dict(ds.observed_cache)
   assert len(ds)==len(sets[split]) and set(ds.im_files)=={r['image'] for r in records if r['usage']==split}
   expected_boxes=stats[split]['boxes'];assert sum(len(r['cls']) for r in ds.labels)==expected_boxes
   assert all(not len(r['cls']) or set(r['cls'].reshape(-1))=={0.} for r in ds.labels)
   nf,nm,ne,nc,n=initial['results'];assert nf==n==len(sets[split]) and nm==nc==0
   dl=torch.utils.data.DataLoader(ds,batch_size=2,num_workers=0,shuffle=False,collate_fn=ds.collate_fn)
   batch=next(iter(dl));shape=list(batch['img'].shape);assert shape==[2,3,640,640]
   again=ObservedDataset(**kwargs);cached=dict(again.observed_cache)
   assert cached['loaded_existing'] and len(again)==len(ds) and again.im_files==ds.im_files
  loader_results[split]=dict(images=len(ds),boxes=expected_boxes,cache_absent_before_first_validation=fresh_before,
   first_scan=initial,second_load=cached,batch_shape=shape,workers=0,verification_threads=1,augmentation=False)
  print(json.dumps(dict(split=split,images=len(ds),boxes=expected_boxes,cache_reuse_matches=True)),flush=True)
 # JPEG validation is permitted only on the copied view; verify no repair changed any image/label.
 for r in records:assert sha(r['image'])==r['image_sha256'] and sha(r['label'])==r['label_sha256']
 for path,expected in source_hashes.items():assert sha(path)==expected
 save(ROOT/'statistics.json',stats)
 writecsv(ROOT/'split_distribution.csv',[dict(usage=k,images=s['images'],positive=s['positive_images'],negative=s['negative_images'],boxes=s['boxes'],
  **{f:s['scenes'][f]['images'] for f in FLAGS}) for k,s in stats.items()])
 known_train=[r for r in records if r['source']=='181531' and r['usage']=='train'];train_times=np.array([r['source_seconds'] for r in known_train])
 gaps=[float(np.abs(train_times-r['source_seconds']).min()) for r in tests]
 verification=dict(status='PASS_FOR_ALLOCATION_AND_LOADING',limitation='Same-session segment holdout; finite similarity review does not prove full independence or absence of all possible leakage.',
  verified_at_utc=datetime.now(timezone.utc).isoformat(),counts={k:len(v) for k,v in sets.items()},all_active_images_assigned=8148,
  all_disjoint=True,source_image_label_pairs_checked=8398,copied_image_label_pairs_checked=8148,original_excluded_omitted=250,
  val_exactly_locked=True,legacy_all_train=True,source_frame_cross_sides=0,test_one_eye_per_source_frame=True,
  test_source_frames=len(tests),test_segments=len({r['segment_id'] for r in tests}),test_physical_sessions=1,
  file_and_pixel_exact_cross_split_groups=duplicate_groups,old_high_priority_pairs_rechecked=len(high),old_recorded_relations_cross_formal_sides=0,
  all_heldout_cores_and_buffers_out_of_train=True,nearest_train_time_gap_seconds=dict(min=min(gaps),median=float(np.median(gaps)),max=max(gaps),not_independence_proof=True),
  current_similarity_queries=len(tests),current_similarity_candidate_pairs=load(ROOT/'analysis/final_similarity_summary.json')['candidate_pairs'],
  current_reviewed_focus_pairs=len(load(ROOT/'analysis/final_pair_visual_observations.json')),unresolved_active_test_groups=0,
  recovery_only_uncertain_groups=['G01','G02'],source_documents_unchanged=True,all_source_and_copy_content_unchanged=True,
  loader=loader_results,ultralytics_version=importlib.metadata.version('ultralytics'),runtime_config=str(USER_CONFIG_DIR),
  caches_written_only_inside_new_version=True,model_instantiated=False,model_training_executed=False,prediction_metrics_used=False,
  validation_script_sha256=sha(Path(__file__)))
 save(ROOT/'verification.json',verification)
 print(json.dumps(dict(status=verification['status'],counts=verification['counts'],test_time_gap=verification['nearest_train_time_gap_seconds']),ensure_ascii=False))

if __name__=='__main__':main()
