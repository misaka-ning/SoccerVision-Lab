from common import *
from datetime import datetime,timezone
import platform

def main():
 assert not (ROOT/'COMPLETED.json').exists(),'Version is sealed; create a new version for changes.'
 m=load(ROOT/'manifest.json');v=load(ROOT/'verification.json');st=load(ROOT/'runtime/html-static-validation.json');ui=load(ROOT/'runtime/browser-validation.json')
 expected=dict(train=4346,val=1223,test=464,buffer=755,heldout_unused=1360)
 assert Counter(r['usage'] for r in m['records'])==expected
 assert v['counts']==expected and v['status']=='PASS_FOR_ALLOCATION_AND_LOADING'
 assert ui['status']=='BROWSER_INTERACTION_PASS' and not ui['checks']['consoleErrors']
 assert sha(ROOT/'review.html')==st['html_sha256']
 assert st['embedded_valid_jpegs']==597 and st['external_dependencies']==[]
 assert load(ROOT/'analysis/archived_contact_history.json')['all_match_original_sha256']
 for p,digest in m['source_documents_sha256'].items():assert sha(p)==digest,'Source document changed: '+p
 for role,count in expected.items():
  actual=(ROOT/'lists'/f'{role}.txt').read_text().splitlines()
  assert len(actual)==count and set(actual)=={r['image'] for r in m['records'] if r['usage']==role}
 media={}
 for r in m['records']:
  media[str(Path(r['image']).relative_to(ROOT))]=r['image_sha256']
  media[str(Path(r['label']).relative_to(ROOT))]=r['label_sha256']
 excluded_index={'COMPLETED.json','analysis/output_files.json'};index=[];size=0
 for p in sorted(ROOT.rglob('*')):
  assert not p.is_symlink(),'Unexpected link in version: '+str(p)
  if not p.is_file():continue
  rel=str(p.relative_to(ROOT))
  if rel in excluded_index:continue
  digest=sha(p)
  if rel in media:assert digest==media[rel],'Media content changed after loader validation: '+rel
  length=p.stat().st_size;size+=length
  index.append(dict(path=rel,bytes=length,sha256=digest))
 assert len(media)==8148*2
 save(ROOT/'analysis/output_files.json',dict(version=ROOT.name,files=index,file_count=len(index),bytes=size,
  scope='Every regular output file except this index and COMPLETED.json, to avoid recursive hashes.',
  media_pairs_rechecked=8148,source_integrity_verification='verification.json'))
 done=dict(status='READY_SAME_SESSION_SEGMENT_HOLDOUT_WITH_DOCUMENTED_LIMITATIONS',
  completed_at_utc=datetime.now(timezone.utc).isoformat(),version_id=ROOT.name,counts=expected,usable_images=8148,
  original_excluded_preserved=250,test_source_frame_moments=464,test_core_segments=8,test_contiguous_blocks=7,
  test_real_physical_sessions=1,test_train_shared_recording='181531',independent_event_count='not_estimated',
  configuration='dataset.yaml',manifest='manifest.csv',review='review.html',report='REPORT.md',reproduce='REPRODUCE.md',
  source_unchanged=True,image_label_bytes_unchanged=True,actual_framework_loading_verified=True,
  model_training_executed=False,model_predictions_used_to_select=False,
  optional_recovery_review_groups=['G01','G02'],withdrawn_candidate_representatives=26,
  existing_weight_training_exposure='unknown',
  html_self_contained_static_verified=True,html_interaction_test='isolated one-file folder over loopback HTTP',
  direct_file_scheme_ui_test='not permitted by automation browser; no bypass attempted',
  python_version=platform.python_version(),script_sha256={p.name:sha(p) for p in sorted((ROOT/'scripts').glob('*.py'))},
  verification_sha256=sha(ROOT/'verification.json'),manifest_sha256=sha(ROOT/'manifest.json'),
  output_index_sha256=sha(ROOT/'analysis/output_files.json'),review_html_sha256=sha(ROOT/'review.html'),
  media_pairs_rechecked_at_seal=8148,output_files_indexed=len(index),output_bytes_indexed=size)
 save(ROOT/'COMPLETED.json',done)
 print(json.dumps(done,ensure_ascii=False))

if __name__=='__main__':main()
