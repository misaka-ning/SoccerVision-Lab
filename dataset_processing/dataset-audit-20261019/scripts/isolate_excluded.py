#!/usr/bin/env python3
"""User-authorized reversible isolation of reviewed_excluded files only.

The audit began read-only. The user's later explicit request authorizes only
moving these 250 images and corresponding labels. Metadata/YAML stay byte exact.
"""
import argparse,hashlib,json,os,shutil,subprocess,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

OUT=Path(__file__).resolve().parents[1]
D=Path('/home/misaka/workspace/datasets')
H=Path('/home/misaka/workspace/script/dataset-reviewer/maintenance')
LOCK_RUNNER=H.parent/'build/release/qt_review_lock_runner'
sys.path.insert(0,str(H));import audit_io as h
OP=OUT/'isolation'

def save(path,x):
    h.save_exclusive(path,(json.dumps(x,ensure_ascii=False,indent=2)+'\n').encode())

def prepare():
    raw=(D/'metadata.csv').read_bytes();parsed=h.csv_parts(raw)
    originals={r['filename']:r for r in json.loads((OUT/'data/inventory.json').read_text())}
    selected=[r for r in parsed['rows'] if r['annotation_status']=='reviewed_excluded']
    assert len(selected)==250 and not (D/'excluded').exists()
    records=[]
    for row in selected:
        assert row['label_review_required']==row['scene_review_required']=='0'
        b=originals[row['图片']];assert not b['usable'] and row==b['meta']
        item=dict(filename=row['图片'],split=row['split'],meta=row)
        for kind,suffix in [('images',None),('labels','.txt')]:
            name=row['图片'] if suffix is None else Path(row['图片']).stem+suffix
            source=h.regular_under(D/kind/row['split']/name,D)
            target=D/'excluded'/kind/row['split']/name
            sha=h.digest(source.read_bytes());expected=b['image_sha256' if kind=='images' else 'label_sha256']
            assert sha==expected and not target.exists()
            item[kind]=dict(original=str(source),isolated=str(target),sha256=sha,
                            backup=str(OP/'backup'/kind/row['split']/name))
        records.append(item)
    OP.mkdir(exist_ok=False)
    plan=dict(authorization='User explicitly requested isolation of the 250 images and labels into a sibling folder after the read-only audit started.',
              created_at_utc=datetime.now(timezone.utc).isoformat(),dataset=str(D),count=250,
              split_counts=dict(Counter(r['split'] for r in selected)),
              metadata_sha256=h.digest(raw),yaml_sha256=h.digest((D/'dataset.yaml').read_bytes()),
              records=records,original_metadata_preserved=True,split_assignment_preserved=True,
              rollback='Restore each isolated path to its original path only when original absent and hash matches; backup copies are also retained under this audit isolation/backup.')
    save(OP/'plan.json',plan)
    (OP/'before-metadata.csv').write_bytes(raw)
    (OP/'before-dataset.yaml').write_bytes((D/'dataset.yaml').read_bytes())
    return plan

def execute(plan):
    assert h.digest((D/'metadata.csv').read_bytes())==plan['metadata_sha256']
    assert h.digest((D/'dataset.yaml').read_bytes())==plan['yaml_sha256']
    assert not (D/'excluded').exists()
    for r in plan['records']:
        for kind in ('images','labels'):
            x=r[kind];s=h.regular_under(Path(x['original']),D)
            assert h.digest(s.read_bytes())==x['sha256']
            b=Path(x['backup']);b.parent.mkdir(parents=True,exist_ok=True)
            assert not b.exists();shutil.copy2(s,b)
            assert h.digest(b.read_bytes())==x['sha256']
    (D/'excluded').mkdir()
    moved=[]
    try:
        with (OP/'journal.jsonl').open('x',encoding='utf-8') as journal:
            for r in plan['records']:
                for kind in ('images','labels'):
                    x=r[kind];s=Path(x['original']);t=Path(x['isolated'])
                    t.parent.mkdir(parents=True,exist_ok=True)
                    assert not t.exists() and h.digest(s.read_bytes())==x['sha256']
                    os.rename(s,t);moved.append(x)
                    journal.write(json.dumps(x,ensure_ascii=False)+'\n');journal.flush()
                    assert not s.exists() and h.digest(t.read_bytes())==x['sha256']
            os.fsync(journal.fileno())
        assert h.digest((D/'metadata.csv').read_bytes())==plan['metadata_sha256']
        assert h.digest((D/'dataset.yaml').read_bytes())==plan['yaml_sha256']
    except BaseException:
        for x in reversed(moved):
            s,t=Path(x['original']),Path(x['isolated'])
            if not s.exists() and t.exists() and h.digest(t.read_bytes())==x['sha256']:os.rename(t,s)
        raise
    result=dict(success=True,status='ISOLATED',images_moved=250,labels_moved=250,
                destination=str(D/'excluded'),split_counts=plan['split_counts'],
                metadata_modified=False,yaml_modified=False,usable_files_moved=0,
                bytes_and_permissions_preserved=True,backup_directory=str(OP/'backup'),
                completed_at_utc=datetime.now(timezone.utc).isoformat())
    save(OP/'result.json',result)
    save(D/'excluded/manifest.json',plan)
    parsed=h.csv_parts((D/'metadata.csv').read_bytes());names={r['filename'] for r in plan['records']}
    # Preserve the exact selected CSV records as archival metadata, not a rewrite.
    text=parsed['records'][0]+parsed['endings'][0]
    for i,r in enumerate(parsed['rows'],1):
        if r['图片'] in names:text+=parsed['records'][i]+parsed['endings'][i]
    (D/'excluded/metadata.csv').write_bytes((b'\xef\xbb\xbf' if parsed['bom'] else b'')+text.encode())
    (D/'excluded/README.md').write_text('''# 已审核但暂不训练的250张参考样本

用户于2026-10-19明确要求隔离。图片和label保持原始字节，内部按images/labels及原train/val/test保存，不自动作为无球负样本。

根目录metadata.csv仍是完整8398张审核历史，本目录metadata.csv为250条原始记录副本。根metadata的reviewed_excluded图片实际路径按本目录manifest.json解析；没有修改原split字段。当前根images/labels只留8148张可用样本。

manifest.json记录原路径、现路径、SHA256和回滚规则；审计目录isolation/backup保留移动前副本。恢复前必须核对哈希和目标冲突，不覆盖任何后续人工修改。
''')
    print(json.dumps(result,ensure_ascii=False,indent=2))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--apply',action='store_true');ap.add_argument('--locked',action='store_true');args=ap.parse_args()
    if not args.apply:
        plan=prepare();print(json.dumps(dict(prepared=True,count=plan['count'],split_counts=plan['split_counts'],plan=str(OP/'plan.json'))));return
    plan=json.loads((OP/'plan.json').read_text())
    if args.locked:execute(plan);return
    locks=[str(D/'metadata.csv')+'.review.lock']+[r['labels']['original']+'.review.lock' for r in plan['records']]
    save(OP/'locks.json',sorted(locks))
    raise SystemExit(subprocess.run([str(LOCK_RUNNER),'--lock-list',str(OP/'locks.json'),'--',sys.executable,str(Path(__file__).resolve()),'--apply','--locked']).returncode)

if __name__=='__main__':main()
