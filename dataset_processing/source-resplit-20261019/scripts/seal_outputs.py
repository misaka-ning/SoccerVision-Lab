#!/usr/bin/env python3
"""Record the verified resplit version without rewriting source data."""
import hashlib,json,os
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
try: os.nice(10)
except OSError: pass
OUT=Path(__file__).resolve().parents[1]
def load(p): return json.loads(p.read_text(encoding='utf-8'))
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()
plan=load(OUT/'plan.json'); result=load(OUT/'result.json'); verified=load(OUT/'verification.json')
assert result['status']==verified['status']=='PASS'
assert result['metadata_sha256']==verified['metadata_sha256']
assert result['yaml_sha256']==verified['yaml_sha256']
for c in plan['configs']: assert sha(Path(c['path']))==c['sha256_after']
assert sha(Path(__file__).with_name('resplit_sources.py'))==result['script_sha256']
assert sha(Path(__file__).with_name('verify_resplit.py'))==verified['script_sha256']
sources=[dict(path=c['path'],sha256_before=c['sha256_before'],sha256_after=c['sha256_after']) for c in plan['configs']]
policy=Path(plan['dataset'])/'SPLIT_POLICY.md'
sources.append(dict(path=str(policy),sha256_after=sha(policy),created=True))
files=[]
for p in sorted(OUT.rglob('*')):
    if not p.is_file() or p.name=='manifest.json' and p.parent==OUT: continue
    assert not p.is_symlink()
    files.append(dict(path=str(p.relative_to(OUT)),bytes=p.stat().st_size,sha256=sha(p)))
manifest=dict(schema_version=1,operation_id=OUT.name,completed_at_utc=datetime.now(timezone.utc).isoformat(),
    status='APPLIED_AND_VERIFIED',authorization=plan['authorization'],
    active_image_and_label_pair_counts=result['active_image_counts'],excluded_pairs_preserved=250,
    moved_pairs=1185,moved_files=2370,metadata_rows=8398,metadata_split_changes=1185,
    source_group_targets={'18:15:31 first27min':'train','legacy':'train','10:47:48':'val','18:13:26':'val'},
    metadata_other_fields_unchanged=True,image_label_content_and_modes_unchanged=True,
    archived_split_values='Historical243train/6val/1test; excluded and not active Test samples.',
    current_canonical_documents=sources,source_provenance_path=str(Path(plan['source_audit'])/'data/provenance.json'),
    source_provenance_sha256=plan['source_provenance_sha256'],
    frozen_audit_rewritten=False,model_training_executed=False,model_or_engine_changed=False,
    checks=dict(transaction='result.json',independent_full_sha_and_file_discovery='verification.json',basic_training_config='validation/train-dry-run.json'),
    implementation_hashes={str(p.relative_to(OUT)):sha(p) for p in sorted((OUT/'scripts').glob('*.py'))},
    outputs=files,output_count=len(files),self_hash_policy='Manifest excludes itself to avoid a recursive digest.',
    backup_directory=str(OUT/'before'),rollback='See plan.json and REPORT.md; hold reviewer locks and check current SHA/conflicts. Never overwrite later edits.')
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(dict(status=manifest['status'],active_counts=result['active_image_counts'],output_files=len(files),
    metadata_sha256=result['metadata_sha256'],manifest=str(OUT/'manifest.json')),ensure_ascii=False))
