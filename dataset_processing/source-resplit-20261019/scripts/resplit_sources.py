#!/usr/bin/env python3
"""Apply the user's explicit recording-based split, with backups and rollback.

Default prepares a frozen plan. --apply acquires the reviewer's Qt locks first.
Only active images/labels are moved. Only metadata.split changes; scenes,
annotation status, notes, source fields, image bytes and label bytes are kept.
"""
import os
os.environ['OMP_NUM_THREADS']='1'
os.environ['OPENBLAS_NUM_THREADS']='1'
try: os.nice(10)
except OSError: pass
import argparse, csv, hashlib, io, json, shutil, stat, subprocess, sys, tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

OUT=Path(__file__).resolve().parents[1]
BASE=Path('/home/misaka/workspace')
DATA=BASE/'datasets'
AUDIT=BASE/'dataset_processing/dataset-audit-20261019'
HELPER=BASE/'script/dataset-reviewer/maintenance'
RUNNER=HELPER.parent/'build/release/qt_review_lock_runner'
sys.dont_write_bytecode=True
sys.path.insert(0,str(HELPER))
import audit_io as h

SOURCES={
 'stereo_20261013_104748_922854_7a88b83e76d9406f8ed02e0ded4f36bb':('10:47:48','val'),
 'stereo_20261013_181326_250178_b15c1f6de79441fc9a59436202b7cc5a':('18:13:26','val'),
 'stereo_20261013_181531_750945_d976724b06a247158bb023f3675e05b4_first27min':('18:15:31 first27min','train'),
 'legacy':('legacy','train'),
}
EXPECTED_COUNTS={'train':6925,'val':1223,'test':0}
OLD_PARAGRAPH='截至2026-10-19，8398张图片已全部完成球框和场景审核：8148张可用，250张已审核但暂不训练，待审0张。现有分集总数为train 8100、val 170、test 128；可用数量分别为7857、164、127。[完整统计](dataset_processing/batch-review-20261016/final-statistics-20261019/REPORT.md)，实时状态以 `datasets/metadata.csv` 为准。'
NEW_PARAGRAPH='截至2026-10-19，8398张图片已全部完成球框和场景审核：8148张可用，250张已隔离至 `datasets/excluded/`，待审0张。按用户指定来源重分后，可用Train为6925张（18:15:31视频及legacy），Val为1223张（10:47:48及18:13:26视频），Test暂空，待独立补采。[当前划分说明](datasets/SPLIT_POLICY.md)及[重分与校验记录](dataset_processing/source-resplit-20261019/REPORT.md)记录当前版本；[此前统计](dataset_processing/batch-review-20261016/final-statistics-20261019/REPORT.md)与[科研审计](dataset_processing/dataset-audit-20261019/AUDIT_REPORT.md)保留为重分前的历史快照。根metadata仍含250条排除历史记录，统计当前集合须先过滤 `reviewed_excluded`。'

def now(): return datetime.now(timezone.utc).isoformat()
def sha(p):
    d=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''): d.update(block)
    return d.hexdigest()
def load(p): return json.loads(p.read_text(encoding='utf-8'))
def save(p,v): h.save_exclusive(p,(json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode())
def atomic(p,raw,mode):
    fd,tmp=tempfile.mkstemp(prefix='.source-resplit-',suffix='.tmp',dir=p.parent)
    try:
        with os.fdopen(fd,'wb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
        os.chmod(tmp,mode); os.replace(tmp,p)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
def source_of(row,record):
    key='legacy' if row['图片'].startswith('legacy_') else record.get('recording_id')
    assert key in SOURCES,(row['图片'],key)
    return key

def prepare():
    assert not (OUT/'plan.json').exists(),'A plan already exists; do not overwrite it.'
    metadata=h.regular_under(DATA/'metadata.csv',DATA)
    raw=metadata.read_bytes(); parsed=h.csv_parts(raw)
    prov=load(AUDIT/'data/provenance.json')['records']
    inv={r['filename']:r for r in load(AUDIT/'data/inventory.json')}
    assert len(parsed['rows'])==8398 and set(inv)=={r['图片'] for r in parsed['rows']}
    records=[]; moves=[]; grouped=defaultdict(Counter)
    for i,row in enumerate(parsed['rows']):
        name=row['图片']; source=source_of(row,prov[name]); is_excluded=row['annotation_status']=='reviewed_excluded'
        assert row['scene_review_required']==row['label_review_required']=='0'
        old=row['split']; new=old if is_excluded else SOURCES[source][1]
        item=dict(index=i,filename=name,source=source,excluded=is_excluded,old_split=old,new_split=new,meta=row,files={})
        root=DATA/'excluded' if is_excluded else DATA
        for kind,filename,hashkey in [('images',name,'image_sha256'),('labels',Path(name).stem+'.txt','label_sha256')]:
            src=h.regular_under(root/kind/old/filename,DATA); dest=root/kind/new/filename
            content_sha=sha(src)
            if kind=='images': assert content_sha==inv[name][hashkey],f'Source image identity changed: {src}'
            item['files'][kind]=dict(before=str(src),after=str(dest),sha256=content_sha,bytes=src.stat().st_size,mode=stat.S_IMODE(src.stat().st_mode))
            if old!=new:
                assert not dest.exists(),f'Destination conflict: {dest}'
                moves.append(dict(filename=name,kind=kind,source=str(src),destination=str(dest),sha256=content_sha,
                    backup=str(OUT/'before/files'/kind/old/filename)))
        records.append(item); grouped[source]['all']+=1; grouped[source]['excluded' if is_excluded else 'usable']+=1
        if i%2000==0: print(json.dumps(dict(stage='snapshot',checked_images=i)),flush=True)
    assert sum(not r['excluded'] for r in records)==8148
    assert Counter(r['new_split'] for r in records if not r['excluded'])=={k:v for k,v in EXPECTED_COUNTS.items() if v}
    assert len(moves)==2370 and sum(r['excluded'] for r in records)==250
    changes={r['filename']:dict(r['meta'],split=r['new_split']) for r in records if r['old_split']!=r['new_split']}
    proposed=h.csv_update(parsed,changes)
    after=h.csv_parts(proposed)
    for before,ar in zip(parsed['rows'],after['rows']):
        assert all(before[k]==ar[k] for k in before if k!='split')
    original_yaml=(DATA/'dataset.yaml').read_bytes()
    assert b'test: images/test\n' in original_yaml
    new_yaml=original_yaml.replace(b'test: images/test\n',
        '# Test暂空，待补采独立视频；空目录不能用于测试评估。\n'.encode()+b'test: images/test\n',1)
    new_yaml='# 2026-10-19 按来源划分：Train=18:15:31+legacy；Val=10:47:48+18:13:26。\n'.encode()+new_yaml
    readme=(BASE/'README.md').read_bytes()
    assert readme.decode().count(OLD_PARAGRAPH)==1
    assert not (DATA/'SPLIT_POLICY.md').exists()
    configs=[(DATA/'metadata.csv',raw,proposed,'metadata.csv'),
             (DATA/'dataset.yaml',original_yaml,new_yaml,'dataset.yaml'),
             (BASE/'README.md',readme,readme.decode().replace(OLD_PARAGRAPH,NEW_PARAGRAPH).encode(),'workspace-README.md')]
    config_records=[]
    for path,before,after_bytes,label in configs:
        backup=OUT/'before'/label; proposed_path=OUT/'proposed'/label
        backup.write_bytes(before); proposed_path.parent.mkdir(exist_ok=True); proposed_path.write_bytes(after_bytes)
        config_records.append(dict(path=str(path),before=str(backup),proposed=str(proposed_path),
            sha256_before=h.digest(before),sha256_after=h.digest(after_bytes),mode=stat.S_IMODE(path.stat().st_mode)))
    cache=[]
    for p in sorted(DATA.rglob('*.cache')):
        if (DATA/'excluded') in p.parents: continue
        h.regular_under(p,DATA)
        cache.append(dict(source=str(p),backup=str(OUT/'before/caches'/p.relative_to(DATA)),sha256=sha(p)))
    archive_reference={str(p):sha(p) for p in (DATA/'excluded/manifest.json',DATA/'excluded/metadata.csv',DATA/'excluded/README.md')}
    plan=dict(created_at_utc=now(),authorization='User explicitly requested Train=18:15:31+legacy, Val=10:47:48+18:13:26, and an empty Test awaiting future collection.',
        dataset=str(DATA),source_audit=str(AUDIT),source_provenance_sha256=sha(AUDIT/'data/provenance.json'),
        source_inventory_sha256=sha(AUDIT/'data/inventory.json'),records=records,moves=moves,configs=config_records,caches=cache,
        expected_active_counts=EXPECTED_COUNTS,source_counts={k:dict(v) for k,v in grouped.items()},
        archived_records_unchanged=True,archive_reference_sha256=archive_reference,
        rollback='Under reviewer locks, move each matching destination back only if original absent; restore config from before snapshots only if current bytes match this plan proposal. Never overwrite later edits. Moved image/label copies also retained in before/files.')
    save(OUT/'plan.json',plan)
    fields=['filename','source','old_split','new_split','excluded','image_before','image_after','label_before','label_after','image_sha256','label_sha256']
    with (OUT/'split_changes.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in records:
            w.writerow(dict(filename=r['filename'],source=r['source'],old_split=r['old_split'],new_split=r['new_split'],excluded=r['excluded'],
                image_before=r['files']['images']['before'],image_after=r['files']['images']['after'],
                label_before=r['files']['labels']['before'],label_after=r['files']['labels']['after'],
                image_sha256=r['files']['images']['sha256'],label_sha256=r['files']['labels']['sha256']))
    print(json.dumps(dict(prepared=True,move_image_label_pairs=len(moves)//2,active_counts=EXPECTED_COUNTS),ensure_ascii=False),flush=True)

def validate(plan):
    rows=h.csv_parts((DATA/'metadata.csv').read_bytes())['rows']
    assert len(rows)==len(plan['records'])==8398
    byname={r['图片']:r for r in rows}
    expected_paths=defaultdict(set); counts=Counter(); sources=defaultdict(set)
    owned_locks=set(load(OUT/'locks.json'))
    for i,r in enumerate(plan['records']):
        current=byname[r['filename']]
        assert current==dict(r['meta'],split=r['new_split']),f'Unexpected metadata edit: {r["filename"]}'
        for kind,entry in r['files'].items():
            p=h.regular_under(Path(entry['after']),DATA)
            assert sha(p)==entry['sha256'],f'Content changed: {p}'
            assert stat.S_IMODE(p.stat().st_mode)==entry['mode']
            if not r['excluded']: expected_paths[(kind,r['new_split'])].add(str(p))
        if not r['excluded']:
            counts[r['new_split']]+=1; sources[r['source']].add(r['new_split'])
        if i%2000==0: print(json.dumps(dict(stage='validate_all8398',checked_images=i)),flush=True)
    for kind in ('images','labels'):
        for split in ('train','val','test'):
            actual={str(p) for p in (DATA/kind/split).iterdir() if (p.is_file() or p.is_symlink()) and str(p) not in owned_locks}
            assert actual==expected_paths[(kind,split)],f'Unexpected physical path set: {kind}/{split}'
    assert counts=={s:n for s,n in EXPECTED_COUNTS.items() if n}
    assert all(groups=={SOURCES[source][1]} for source,groups in sources.items())
    for p,expected in plan['archive_reference_sha256'].items(): assert sha(Path(p))==expected
    for c in plan['configs']: assert sha(Path(c['path']))==c['sha256_after']
    return dict(status='PASS',checked_images=8398,checked_labels=8398,active_image_counts=EXPECTED_COUNTS,
        excluded_images=250,unchanged_image_and_label_bytes=True,scene_and_review_fields_unchanged=True,
        metadata_only_split_modified=True,source_groups_cross_splits=0,test_reserved_empty=True,
        original_archive_unchanged=True,original_frozen_audit_untouched=True,validated_at_utc=now())

def policy_text(plan):
    return '''# 当前数据集划分（2026-10-19）

按用户指定来源划分，适用于images/labels中的8148张可用图片。左右目各计1张，球框、四类场景和人工审核结果保持。

| 来源 | 当前集合 | 可用图片 | 隔离图片（不参与划分） |
| --- | --- | ---: | ---: |
| 2026-10-13 18:15:31（前27分钟） | Train | 6212 | 226 |
| legacy | Train | 713 | 1 |
| 2026-10-13 10:47:48 | Val | 1154 | 22 |
| 2026-10-13 18:13:26 | Val | 69 | 1 |
| 合计 | Train6925 / Val1223 / Test0 | 8148 | 250 |

`images/test/`和`labels/test/`保留为空目录，待后续独立采集。dataset.yaml的test路径仍明确指向这个空目录；当前没有Test指标，不能把Val结果记成Test结果。Train/Val仍由同一个dataset.yaml读取。

根metadata.csv保留完整8398条审核历史。只修改1185条可用样本的split，保持行顺序、来源字段、四类场景、审核状态和备注。统计当前训练/验证数据必须过滤annotation_status=reviewed_excluded；250条排除记录及excluded下的文件、metadata和隔离manifest保持原样，其中原split仅表示隔离时的历史位置，并不构成当前Test数据。

legacy_train/val/test文件名前缀是旧导入命名，当前集合以目录和metadata.split为准；本次没有重命名图片，也没有修改任何label内容。

此前科研审计是重分前冻结快照，包含旧split和旧绝对路径，不应当作当前划分报告。其已打包缩略图和证据页仍是历史证据。本次来源归组使用该审计中经图SHA验证的provenance，不改写旧审计。按视频分组解决已知录像被拆到Train/Val的问题，但不代表重新获得科研审计PASS，也不补足尚未采集的独立Test。

执行清单、前后映射、备份、日志和独立验证见 ../dataset_processing/source-resplit-20261019/ 。不要直接重跑迁移脚本。回退前须核对当前文件SHA及目标冲突，保留任何后续人工修改。
'''

def apply(plan):
    assert not (OUT/'result.json').exists(),'Already applied; do not rerun.'
    for c in plan['configs']:
        assert sha(Path(c['path']))==c['sha256_before'],f'Concurrent config modification: {c["path"]}'
        assert sha(Path(c['proposed']))==c['sha256_after']
    assert not (DATA/'SPLIT_POLICY.md').exists()
    for r in plan['records']:
        for entry in r['files'].values():
            assert sha(h.regular_under(Path(entry['before']),DATA))==entry['sha256'],'Concurrent image/label modification'
    for m in plan['moves']:
        src=Path(m['source']); dest=Path(m['destination']); backup=Path(m['backup'])
        assert not dest.exists() and not backup.exists()
        backup.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,backup)
        assert sha(backup)==m['sha256']
    actual_caches={str(p) for p in DATA.rglob('*.cache') if DATA/'excluded' not in p.parents}
    assert actual_caches=={c['source'] for c in plan['caches']},'Cache inventory changed'
    moved=[]; configs_written=[]; caches_moved=[]; policy_created=False
    try:
        with (OUT/'journal.jsonl').open('x',encoding='utf-8') as journal:
            for n,m in enumerate(plan['moves'],1):
                src,dest=Path(m['source']),Path(m['destination'])
                assert not dest.exists()
                os.rename(src,dest); moved.append(m)
                journal.write(json.dumps(dict(step='move',**m),ensure_ascii=False)+'\n'); journal.flush()
                if n%500==0: print(json.dumps(dict(stage='move',files=n,total=len(plan['moves']))),flush=True)
            for c in plan['caches']:
                src,dest=Path(c['source']),Path(c['backup']); assert sha(src)==c['sha256']
                dest.parent.mkdir(parents=True,exist_ok=True); assert not dest.exists()
                os.rename(src,dest); caches_moved.append(c)
            for c in plan['configs']:
                assert sha(Path(c['path']))==c['sha256_before']
                atomic(Path(c['path']),Path(c['proposed']).read_bytes(),c['mode']); configs_written.append(c)
                journal.write(json.dumps(dict(step='config',path=c['path'],sha256_after=c['sha256_after']))+'\n'); journal.flush()
            policy_created=True; atomic(DATA/'SPLIT_POLICY.md',policy_text(plan).encode(),0o664)
            os.fsync(journal.fileno())
        result=validate(plan)
    except BaseException:
        for c in reversed(configs_written):
            p=Path(c['path'])
            if sha(p)==c['sha256_after']: atomic(p,Path(c['before']).read_bytes(),c['mode'])
        for m in reversed(moved):
            src,dest=Path(m['source']),Path(m['destination'])
            if not src.exists() and dest.exists() and sha(dest)==m['sha256']: os.rename(dest,src)
        for c in reversed(caches_moved):
            src,dest=Path(c['source']),Path(c['backup'])
            if not src.exists() and dest.exists() and sha(dest)==c['sha256']: os.rename(dest,src)
        if policy_created and (DATA/'SPLIT_POLICY.md').exists(): (DATA/'SPLIT_POLICY.md').unlink()
        save(OUT/'rollback.json',dict(rolled_back=True,at_utc=now(),reason='Exception during transaction; snapshots and journal retained.'))
        raise
    result.update(moved_image_label_pairs=len(plan['moves'])//2,moved_files=len(plan['moves']),
        metadata_sha256=sha(DATA/'metadata.csv'),yaml_sha256=sha(DATA/'dataset.yaml'),script_sha256=sha(Path(__file__)),
        cache_files_relocated=len(caches_moved),backup_directory=str(OUT/'before'),model_training_executed=False)
    save(OUT/'result.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--apply',action='store_true'); parser.add_argument('--locked',action='store_true'); args=parser.parse_args()
    if not args.apply: prepare(); return
    plan=load(OUT/'plan.json')
    if args.locked: apply(plan); return
    lockpaths={str(DATA/'metadata.csv')+'.review.lock',str(DATA/'dataset.yaml')+'.review.lock'}
    for r in plan['records']:
        if not r['excluded']:
            lockpaths.update(r['files']['labels'][k]+'.review.lock' for k in ('before','after'))
    locks=OUT/'locks.json'; save(locks,sorted(lockpaths))
    raise SystemExit(subprocess.run([str(RUNNER),'--lock-list',str(locks),'--',sys.executable,str(Path(__file__).resolve()),'--apply','--locked']).returncode)

if __name__=='__main__': main()
