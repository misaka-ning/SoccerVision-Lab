from common import *
import shutil
from datetime import datetime,timezone

def main():
 assert load(ROOT/'analysis/curator_completion.json')['status']=='SELECTION_VISUAL_REVIEW_COMPLETE'
 assert not (ROOT/'MATERIALIZED.json').exists(),'Already materialized; do not overwrite a version.'
 allocation=load(ROOT/'analysis/allocation.json');all_rows=load(ROOT/'analysis/source_inventory.json');guard=load(ROOT/'analysis/reused_evidence.json')['source_hashes']
 for path,expected in guard.items():assert sha(path)==expected,'Source document changed: '+path
 roles=['train','val','test','buffer','heldout_unused']
 for role in roles:
  base=ROOT if role in ['train','val','test'] else ROOT/'reserved'
  for kind in ['images','labels']:(base/kind/role).mkdir(parents=True,exist_ok=True)
 journal=ROOT/'analysis/copy_journal.jsonl';manifest=[]
 with journal.open('x',encoding='utf-8') as log:
  for n,r in enumerate(allocation,1):
   base=ROOT if r['usage'] in ['train','val','test'] else ROOT/'reserved'
   ip=base/'images'/r['usage']/r['filename'];lp=base/'labels'/r['usage']/(Path(r['filename']).stem+'.txt')
   for source,dest,expected in [(Path(r['source_image']),ip,r['image_sha256']),(Path(r['source_label']),lp,r['label_sha256'])]:
    assert sha(source)==expected,'Cached source identity changed; stop before using stale features: '+str(source)
    if dest.exists():assert sha(dest)==expected
    else:shutil.copy2(source,dest)
    assert sha(dest)==expected
    assert source.stat().st_ino!=dest.stat().st_ino,'Copies must not be hardlinks.'
   entry=dict(filename=r['filename'],original_image=r['source_image'],original_label=r['source_label'],original_split=r['source_split'],
    usage=r['usage'],image=str(ip),label=str(lp),recording_id=r['recording_id'],session_id=r['session_id'],session_id_type=r['session_id_type'],
    source=r['source'],source_frame_idx=r['frame'],source_seconds=r['seconds'],source_fps=r['fps'],eye=r['eye'],
    segment_id=r['segment_id'],heldout_block_id=r['heldout_block_id'],frame_unit_id=f'{r["recording_id"]}:{r["frame"]}' if r['frame'] is not None else 'legacy:'+r['filename'],
    image_sha256=r['image_sha256'],pixel_sha256=r['pixel_sha256'],label_sha256=r['label_sha256'],
    allocation_reason=r['reason'],review_group=r['review_group'],eval_subset=r['eval_subset'],
    annotation_status=r['annotation_status'],box_count=len(r['boxes']),**r['flags'])
   manifest.append(entry);log.write(json.dumps(dict(filename=r['filename'],usage=r['usage'],image=str(ip),label=str(lp)),ensure_ascii=False)+'\n')
   if n%1000==0:log.flush();print(json.dumps(dict(copied_pairs=n,total=len(allocation))),flush=True)
 for role in roles:
  rr=[r for r in manifest if r['usage']==role]
  if role=='test':rr.sort(key=lambda r:(r['source_seconds'],r['eye']))
  (ROOT/'lists'/f'{role}.txt').write_text(''.join(r['image']+'\n' for r in rr),encoding='utf-8')
 (ROOT/'lists/future_independent_test.txt').write_text('')
 writecsv(ROOT/'manifest.csv',manifest)
 save(ROOT/'manifest.json',dict(schema_version=1,version_id=ROOT.name,seed=SEED,evaluation_kind='same_session_segment_holdout',
  session_facts='SOURCE_FACTS.json',original_dataset=str(DATA),source_documents_sha256=guard,records=manifest,
  pixel_hash_reuse='Old decoded RGB hash reused only after raw-image SHA equality checked for every source/copy.',
  copied_not_linked=True,original_250_excluded_copied=False,source_data_modified=False))
 source_meta=csvrows(ROOT/'analysis/source-metadata.csv');lookup={r['filename']:r for r in manifest}
 formal=[]
 for r in source_meta:
  m=lookup.get(r['图片'])
  if m and m['usage'] in ['train','val','test']:formal.append(dict(r,split=m['usage']))
 writecsv(ROOT/'metadata.csv',formal,list(source_meta[0]))
 # Auxiliary stereo list: one representative per frame remains the primary Test.
 source_units=defaultdict(dict)
 for r in all_rows:
  if r['source']=='181531':source_units[r['frame']][r['eye']]=r
 pairs=[]
 for r in [r for r in manifest if r['usage']=='test']:
  out=dict(frame_unit_id=r['frame_unit_id'],source_frame_idx=r['source_frame_idx'],source_seconds=r['source_seconds'],
           chosen_eye=r['eye'],chosen_image=r['image'],segment_id=r['segment_id'],physical_session=r['session_id'])
  for eye in ['left','right']:
   source=source_units[r['source_frame_idx']].get(eye);current=lookup.get(source['filename']) if source else None
   out[eye+'_image']=current['image'] if current else '';out[eye+'_label']=current['label'] if current else ''
   out[eye+'_status']=current['usage'] if current else 'original_excluded' if source and source['excluded'] else 'missing'
  out['both_usable_available']=bool(out['left_image'] and out['right_image']);pairs.append(out)
 writecsv(ROOT/'lists/test_stereo_pairs.csv',pairs)
 excluded=[dict(filename=r['filename'],original_image=r['source_image'],original_label=r['source_label'],
   original_split=r['source_split'],status=r['annotation_status'],image_sha256=r['image_sha256'],label_sha256=r['label_sha256']) for r in all_rows if r['excluded']]
 writecsv(ROOT/'original_excluded_reference.csv',excluded)
 import yaml
 config=dict(path=str(ROOT),train='lists/train.txt',val='lists/val.txt',test='lists/test.txt',nc=1,names={0:'football'})
 (ROOT/'dataset.yaml').write_text('# Same-session segment holdout; original source and old split preserved.\n'+yaml.safe_dump(config,allow_unicode=True,sort_keys=False),encoding='utf-8')
 init=ROOT/'initialization';init.mkdir(exist_ok=True)
 arch=Path('/home/misaka/workspace/baseline/original_model.yaml');shutil.copy2(arch,init/'yolo26s_from_scratch.yaml')
 train=yaml.safe_load(Path('/home/misaka/workspace/script/model-training/config/train.yaml').read_text())
 train.update(model=str(init/'yolo26s_from_scratch.yaml'),data=str(ROOT/'dataset.yaml'),pretrained=False,
  project='/home/misaka/workspace/experiments/train',name='same_session_holdout_v1_from_scratch',workers=0,amp=False)
 (ROOT/'train_from_scratch.example.yaml').write_text('# Example only; no model built/trained. Architecture-only initialization avoids reusing unknown old weights.\n'+yaml.safe_dump(train,allow_unicode=True,sort_keys=False),encoding='utf-8')
 weights=[]
 for root in [Path('/home/misaka/workspace/baseline'),Path('/home/misaka/workspace/experiments')]:
  if not root.exists():continue
  for p in root.rglob('*.pt'):
   weights.append(dict(path=str(p),sha256=sha(p),exposure_to_current_test='unknown',
    evidence='No complete, verifiable training image membership supplied; checkpoint date/class metadata alone is not a membership audit.'))
 save(ROOT/'weight_exposure.json',dict(weights=weights,checkpoint_pickle_loaded=False,
  rule='Moving images now cannot undo prior training exposure. A weight that saw any heldout core/buffer is not unseen-test initialization. Formal comparison must restart from a verified unexposed initialization.',
  safe_architecture_only_example='train_from_scratch.example.yaml'))
 save(ROOT/'evaluation_protocol.json',dict(primary_subset='same_session_segment_holdout_v1',primary_test='lists/test.txt',
  physical_test_sessions=1,shared_test_train_session='session_20261013_181531',independent_events_not_estimated=True,
  reporting_units=['image_count','source_frame_unit_count','segment_count','contiguous_heldout_block_count','physical_session_count'],
  stereo_auxiliary='lists/test_stereo_pairs.csv; two eyes are correlated, not two independent events.',
  future_subset=dict(name='future_independent_session_test',status='not_collected',list='lists/future_independent_test.txt',report_separately=True),
  scene_labels='Image-level multi-label; do not assign a multi-ball image flag to every individual box.',
  no_training_or_prediction_metrics_used_in_selection=True))
 for path,expected in guard.items():assert sha(path)==expected
 save(ROOT/'MATERIALIZED.json',dict(status='COPIED_PENDING_FRAMEWORK_VALIDATION',at_utc=datetime.now(timezone.utc).isoformat(),
  counts=dict(Counter(r['usage'] for r in manifest)),copy_method='shutil.copy2, independent regular files; full source and target SHA checked',
  original_source_unchanged=True,original_excluded_not_copied=True,manifest_sha256=sha(ROOT/'manifest.json')))
 print(json.dumps(load(ROOT/'MATERIALIZED.json'),ensure_ascii=False))

if __name__=='__main__':main()
