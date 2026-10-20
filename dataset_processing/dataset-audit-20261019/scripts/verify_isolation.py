#!/usr/bin/env python3
"""Independent read-only validation of the user-authorized excluded-file isolation."""
import os
os.environ['OMP_NUM_THREADS']='1'
try: os.nice(10)
except OSError: pass
import csv, hashlib, json, stat, time
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

BASE=Path('/home/misaka/workspace')
DATA=BASE/'datasets'
OUT=BASE/'dataset_processing/dataset-audit-20261019'
ISO=OUT/'isolation'
EXPECTED_METADATA='cb2386ef97c2f864cad27adf8fc06dc6fc74cea2caf828f32a685abc05985ef9'
EXPECTED_YAML='7781d543cc43364f2a2598ff596adb05a8e80b4547af40195665565a8eef05b6'
EXPECTED_SPLITS={'train':243,'val':6,'test':1}

def sha(b): return hashlib.sha256(b).hexdigest()
def load(p): return json.loads(p.read_text(encoding='utf-8'))
def csvrows(p):
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
def files(p): return set(str(x) for x in p.rglob('*') if x.is_file() or x.is_symlink())
def timestamp(): return datetime.now(timezone.utc).isoformat()

def main():
    started=timestamp(); t=time.monotonic(); failures=[]; checks={}
    def check(name,ok,evidence):
        checks[name]={'passed':bool(ok),'evidence':evidence}
        if not ok: failures.append(name)
    plan=load(ISO/'plan.json'); result=load(ISO/'result.json'); manifest=load(DATA/'excluded/manifest.json')
    inv=load(OUT/'data/inventory.json'); base_summary=load(OUT/'data/inventory-summary.json')
    excluded=[r for r in inv if r['meta']['annotation_status']=='reviewed_excluded']
    usable=[r for r in inv if r['usable']]
    check('plan_manifest_exact_content',plan==manifest,{'plan_sha256':sha((ISO/'plan.json').read_bytes()),'manifest_sha256':sha((DATA/'excluded/manifest.json').read_bytes())})
    check('plan_count_and_split',len(plan['records'])==250 and plan['count']==250 and plan['split_counts']==EXPECTED_SPLITS,{'count':len(plan['records']),'split_counts':plan['split_counts']})
    check('baseline_partition',len(inv)==8398 and len(usable)==8148 and len(excluded)==250 and len(usable)+len(excluded)==len(inv),{'all':len(inv),'usable':len(usable),'excluded':len(excluded)})
    check('declared_result',result.get('success') is True and result.get('images_moved')==250 and result.get('labels_moved')==250 and result.get('usable_files_moved')==0, result)
    key=lambda r:(r['split'],r['filename'])
    plan_map={key(r):r for r in plan['records']}; ex_map={key(r):r for r in excluded}
    check('plan_exact_excluded_records',set(plan_map)==set(ex_map) and len(plan_map)==250 and all(p['meta']==ex_map[k]['meta'] for k,p in plan_map.items()),{'unique_plan_keys':len(plan_map),'exact_meta_records':sum(k in ex_map and p['meta']==ex_map[k]['meta'] for k,p in plan_map.items())})
    mapped_hashes={'images':[],'labels':[]}; byte_errors=[]; path_errors=[]; backup_errors=[]; mode_errors=[]
    mapped_file_records=[]; original_absent=0; archive_files=0; backup_files=0; total_bytes=0
    for i,r in enumerate(inv):
        is_excluded=r['meta']['annotation_status']=='reviewed_excluded'
        p=plan_map.get(key(r)) if is_excluded else None
        for plural,singular in (('images','image'),('labels','label')):
            original=Path(r[f'{singular}_path']); expected_sha=r[f'{singular}_sha256']
            actual=Path(p[plural]['isolated']) if is_excluded else original
            expected_original=DATA/plural/r['split']/(r['filename'] if plural=='images' else Path(r['filename']).stem+'.txt')
            expected_archive=DATA/'excluded'/plural/r['split']/expected_original.name
            expected_backup=ISO/'backup'/plural/r['split']/expected_original.name
            if original!=expected_original or (is_excluded and (Path(p[plural]['original'])!=original or actual!=expected_archive or Path(p[plural]['backup'])!=expected_backup or p[plural]['sha256']!=expected_sha)):
                path_errors.append({'original':str(original),'actual':str(actual),'error':'mapping differs from baseline-derived path or SHA'})
            if is_excluded:
                if not os.path.lexists(original): original_absent+=1
                else: path_errors.append({'original':str(original),'error':'excluded original path still exists'})
            try:
                if actual.is_symlink(): path_errors.append({'actual':str(actual),'error':'symbolic link unexpected'})
                raw=actual.read_bytes(); current_sha=sha(raw); total_bytes+=len(raw)
                if current_sha!=expected_sha: byte_errors.append({'path':str(actual),'expected_sha256':expected_sha,'actual_sha256':current_sha})
                mapped_hashes[plural].append(f'{original}\t{current_sha}\n')
                record={'index':r['index'],'kind':singular,'excluded':is_excluded,'original_path':str(original),'current_path':str(actual),'sha256':current_sha,'matches_baseline':current_sha==expected_sha,'bytes':len(raw)}
                if is_excluded:
                    archive_files+=1; backup=Path(p[plural]['backup'])
                    if backup.is_symlink(): path_errors.append({'backup':str(backup),'error':'symbolic link unexpected'})
                    back=backup.read_bytes(); backup_files+=1
                    record['backup_path']=str(backup); record['backup_sha256']=sha(back); record['backup_bytes_identical']=raw==back
                    if raw!=back: backup_errors.append({'archive':str(actual),'backup':str(backup),'error':'raw bytes differ'})
                    mode_a=stat.S_IMODE(actual.stat().st_mode); mode_b=stat.S_IMODE(backup.stat().st_mode)
                    if mode_a!=mode_b: mode_errors.append({'archive':str(actual),'backup':str(backup),'archive_mode':oct(mode_a),'backup_mode':oct(mode_b)})
                mapped_file_records.append(record)
            except Exception as e:
                byte_errors.append({'path':str(actual),'error':f'{type(e).__name__}: {e}'})
        if (i+1)%1000==0 or i+1==len(inv): print(json.dumps({'verified_samples':i+1,'total_samples':len(inv),'elapsed_seconds':round(time.monotonic()-t,2)}),flush=True)
    check('all8398_image_label_sha_match_baseline',len(mapped_file_records)==16796 and not byte_errors,{'checked_files':len(mapped_file_records),'bytes_read_current':total_bytes,'errors':byte_errors})
    check('all500_archived_paths_and_original_absence',archive_files==500 and original_absent==500 and not path_errors,{'archive_files':archive_files,'original_paths_absent':original_absent,'errors':path_errors})
    check('all500_archive_backup_bytes_identical',backup_files==500 and not backup_errors,{'checked_backup_files':backup_files,'errors':backup_errors})
    check('archive_backup_modes_match',not mode_errors,{'errors':mode_errors,'note':'compares moved files with preserved backup; original pre-move permission state was not in baseline inventory'})
    for plural,singular in (('images','image'),('labels','label')):
        active_expected={r[f'{singular}_path'] for r in usable}
        active_actual=files(DATA/plural)
        archive_expected={p[plural]['isolated'] for p in plan['records']}; archive_actual=files(DATA/'excluded'/plural)
        backup_expected={p[plural]['backup'] for p in plan['records']}; backup_actual=files(ISO/'backup'/plural)
        check(f'active_{plural}_exact8148',active_actual==active_expected and len(active_actual)==8148,{'actual_count':len(active_actual),'missing':sorted(active_expected-active_actual),'extra':sorted(active_actual-active_expected)})
        check(f'archive_{plural}_exact250',archive_actual==archive_expected and len(archive_actual)==250,{'actual_count':len(archive_actual),'missing':sorted(archive_expected-archive_actual),'extra':sorted(archive_actual-archive_expected)})
        check(f'backup_{plural}_exact250',backup_actual==backup_expected and len(backup_actual)==250,{'actual_count':len(backup_actual),'missing':sorted(backup_expected-backup_actual),'extra':sorted(backup_actual-backup_expected)})
        active_splits=dict(Counter(Path(p).parent.name for p in active_actual)); archive_splits=dict(Counter(Path(p).parent.name for p in archive_actual))
        check(f'archive_{plural}_split243_6_1',archive_splits==EXPECTED_SPLITS,{'active_split_counts':active_splits,'archive_split_counts':archive_splits})
    current_meta=csvrows(DATA/'metadata.csv'); archive_meta=csvrows(DATA/'excluded/metadata.csv')
    meta_sha=sha((DATA/'metadata.csv').read_bytes()); yaml_sha=sha((DATA/'dataset.yaml').read_bytes())
    check('canonical_metadata_exact8398_records',current_meta==[r['meta'] for r in inv] and len(current_meta)==8398,{'record_count':len(current_meta),'annotation_statuses':dict(Counter(r['annotation_status'] for r in current_meta))})
    check('archived_metadata_exact250_original_records',archive_meta==[r['meta'] for r in excluded] and len(archive_meta)==250,{'record_count':len(archive_meta),'split_counts':dict(Counter(r['split'] for r in archive_meta)),'metadata_sha256':sha((DATA/'excluded/metadata.csv').read_bytes())})
    check('metadata_yaml_sha_unchanged',meta_sha==EXPECTED_METADATA==plan['metadata_sha256'] and yaml_sha==EXPECTED_YAML==plan['yaml_sha256'],{'metadata_sha256':meta_sha,'yaml_sha256':yaml_sha})
    aggregate_image_sha=sha(''.join(mapped_hashes['images']).encode()); aggregate_label_sha=sha(''.join(mapped_hashes['labels']).encode())
    check('mapped_hash_aggregates_match_baseline',aggregate_image_sha==base_summary['aggregate_hashes']['image_sha_manifest'] and aggregate_label_sha==base_summary['aggregate_hashes']['label_sha_manifest'],{'image_sha_manifest':aggregate_image_sha,'label_sha_manifest':aggregate_label_sha})
    check('baseline_inventory_frozen',sha((OUT/'data/inventory.json').read_bytes())==base_summary['feature_artifact_sha256']['data/inventory.json'],{'inventory_sha256':sha((OUT/'data/inventory.json').read_bytes())})
    success=not failures
    verification={'status':'PASS' if success else 'FAIL','success':success,'started_at_utc':started,'finished_at_utc':timestamp(),'elapsed_seconds':time.monotonic()-t,'scope':'Independent post-isolation verification of the later user-authorized narrow file move. Baseline audit remains frozen. Canonical metadata retains all8398 review records; excluded paths resolve through the isolation manifest.','authorization':plan['authorization'],'method':'Single process nice10, read-only file bytes; every image and label checked against frozen baseline SHA256; each archive/backup pair compared directly as raw bytes; exact path-set and CSV-record comparisons. No decode rerun is necessary after byte identity is established.','implementation':str(Path(__file__)),'implementation_sha256':sha(Path(__file__).read_bytes()),'checks':checks,'failed_checks':failures,'mapped_file_records':mapped_file_records,'baseline_interpretation':'pre-isolation:8398 active including250 excluded; post-isolation:8148 active+250 archived. Existing metadata is intentionally the full audit ledger and must not be interpreted as8148 active-path entries plus250 missing files.'}
    (ISO/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 250张已排除样本隔离独立核验','',f'结论：**{"PASS" if success else "FAIL"}**。核验时间：{verification["finished_at_utc"]}。','',
           '本次核验针对用户在只读审计之后明确授权的窄范围文件移动：250张 `reviewed_excluded` 图片及其250份label移至 `datasets/excluded/`，备份保留在本审计的 `isolation/backup/`。原始审计baseline、metadata、YAML、split字段和8148张可用样本均按冻结基线核验。','',
           '| 检查 | 结果 |','| --- | --- |',
           f'| 8398张图片及8398份label与冻结基线逐SHA256一致 | {"通过" if checks["all8398_image_label_sha_match_baseline"]["passed"] else "失败"} |',
           f'| 500份隔离文件与500份备份逐字节一致 | {"通过" if checks["all500_archive_backup_bytes_identical"]["passed"] else "失败"} |',
           f'| 250张原图片路径及250份原label路径全部不存在 | {"通过" if checks["all500_archived_paths_and_original_absence"]["passed"] else "失败"} |',
           f'| active images / labels 精确各8148，无额外或缺失文件 | {"通过" if checks["active_images_exact8148"]["passed"] and checks["active_labels_exact8148"]["passed"] else "失败"} |',
           f'| excluded images / labels 精确各250，train243 / val6 / test1 | {"通过" if checks["archive_images_split243_6_1"]["passed"] and checks["archive_labels_split243_6_1"]["passed"] else "失败"} |',
           f'| canonical metadata完整保留8398原始记录，隔离metadata精确250原始记录 | {"通过" if checks["canonical_metadata_exact8398_records"]["passed"] and checks["archived_metadata_exact250_original_records"]["passed"] else "失败"} |',
           f'| metadata及dataset.yaml字节SHA不变 | {"通过" if checks["metadata_yaml_sha_unchanged"]["passed"] else "失败"} |','',
           '迁移前原始训练目录包含8398张，其中250张已排除；迁移后active目录仅8148张可用样本，另250张通过归档manifest解析。`datasets/metadata.csv`仍是8398条全量审核记录，不能把已归档记录计为丢失文件。归档样本仍是排除参考，空label不自动成为负样本。','',
           f'- metadata SHA256：`{meta_sha}`。',f'- dataset.yaml SHA256：`{yaml_sha}`。',
           '- 全部逐文件哈希、路径、分集与备份证据见 [verification.json](./verification.json)。',
           '- 本核验只读canonical数据；没有重写标注、场景、审核状态或分集，没有训练或模型推理。','']
    if failures: lines.extend(['失败检查：'+', '.join(failures),''])
    (ISO/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'success':success,'status':verification['status'],'failed_checks':failures,'elapsed_seconds':verification['elapsed_seconds']},ensure_ascii=False),flush=True)
    if not success: raise SystemExit(1)

if __name__=='__main__': main()
