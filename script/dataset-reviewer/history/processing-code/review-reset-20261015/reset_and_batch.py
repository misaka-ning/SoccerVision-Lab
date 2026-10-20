#!/usr/bin/env python3
"""Reset all review states and create immutable batches without copying a dataset."""
import argparse, csv, hashlib, io, json, math, subprocess, sys
from collections import Counter, OrderedDict
from pathlib import Path
from datetime import datetime, timezone
from PIL import Image

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent/'confidence-review-20261014'
sys.path.insert(0, str(SHARED))
import audit_io as helpers

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dataset',type=Path,default=Path('/home/misaka/workspace/datasets'));parser.add_argument('--locked',action='store_true');args=parser.parse_args()
    root=args.dataset.resolve()
    if (HERE/'reset-result.json').exists():
        print((HERE/'reset-result.json').read_text());return
    if not args.locked:
        rows=helpers.csv_parts((root/'metadata.csv').read_bytes())['rows']
        locks=sorted(str(root/'labels'/r['split']/(Path(r['图片']).stem+'.txt'))+'.review.lock' for r in rows)
        locks.append(str(root/'metadata.csv')+'.review.lock')
        write_json(HERE/'locks.json', locks)
        write_json(HERE/'expected-names.json', sorted(r['图片'] for r in rows))
        command=[str(SHARED/'qt_review_lock_runner'),'--lock-list',str(HERE/'locks.json'),'--',sys.executable,str(Path(__file__).resolve()),'--dataset',str(root),'--locked']
        raise SystemExit(subprocess.run(command).returncode)
    path=root/'metadata.csv';raw=path.read_bytes();parsed=helpers.csv_parts(raw);rows=parsed['rows']
    assert sorted(r['图片'] for r in rows)==json.loads((HERE/'expected-names.json').read_text()), 'Dataset membership changed while acquiring locks'
    assert not (HERE/'before/metadata.csv').exists(), 'Reset backup already exists; inspect before retrying'
    helpers.save_exclusive(HERE/'before/metadata.csv',raw)
    helpers.save_exclusive(HERE/'before/dataset.yaml',(root/'dataset.yaml').read_bytes())
    original=[];after=[];updates={};groups=OrderedDict()
    for index,r in enumerate(rows):
        name=r['图片'];ip=helpers.regular_under(root/'images'/r['split']/name,root);lp=helpers.regular_under(root/'labels'/r['split']/(Path(name).stem+'.txt'),root)
        label=lp.read_bytes();image=ip.read_bytes();errors=[]
        with Image.open(io.BytesIO(image)) as im:width,height=im.size
        try:
            boxes=helpers.label_boxes(label,boundary_tolerance=1e-6)
        except (ValueError,UnicodeError) as exc:
            boxes=[];errors=[str(exc)]
        box_records=[{'box_index':bi,'xywhn':b[1:],'xyxy':[(b[1]-b[3]/2)*width,(b[2]-b[4]/2)*height,(b[1]+b[3]/2)*width,(b[2]+b[4]/2)*height]} for bi,b in enumerate(boxes)]
        record={'index':index,'filename':name,'图片':name,'split':r['split'],'image_path':str(ip),'label_path':str(lp),'width':width,'height':height,'image_sha256':helpers.digest(image),'label_sha256':helpers.digest(label),'label_text':label.decode('utf-8',errors='replace'),'boxes':box_records,'parse_errors':errors,'meta':dict(r)}
        original.append(record)
        new=dict(r);new['label_review_required']='1';new['scene_review_required']='1'
        new['annotation_status']='auto_label_needs_review' if label.strip() else ('needs_manual_bbox_annotation' if r['annotation_status']=='needs_manual_bbox_annotation' else 'needs_visibility_review')
        marker='2026-10-15 用户要求全量重新审核：此前通过状态撤销；助手只做候选标注预审，球框及四类分类均待用户复查通过。'
        if marker not in new['label_review_note']:new['label_review_note']=(new['label_review_note']+' '+marker).strip()
        updates[name]=new;after.append(dict(record,meta=new))
        key=(r['source_video'],r['source_frame_idx']) if r.get('source_video') and r.get('source_frame_idx') else ('single',name)
        groups.setdefault(key,[]).append(record)
    # Keep source-frame stereo pairs together. First-fit packing fills 1000-image
    # batches while preserving first-occurrence order as far as possible.
    batches=[]
    for records in groups.values():
        assert len(records)<=1000
        dest=next((b for b in batches if len(b)+len(records)<=1000),None)
        if dest is None:dest=[];batches.append(dest)
        dest.extend(records)
    assert sorted(r['filename'] for b in batches for r in b)==sorted(updates)
    assert len(batches)==math.ceil(len(rows)/1000)
    assert all(len(b)==1000 for b in batches[:-1])
    out=HERE/'batches';out.mkdir()
    manifest=[]
    for number,batch in enumerate(batches,1):
        batch.sort(key=lambda r:r['index'])
        (out/f'batch-{number:03d}.txt').write_text(''.join(r['filename']+'\n' for r in batch))
        subset=[after[r['index']] for r in batch]
        write_json(out/f'batch-{number:03d}-inventory.json',subset)
        for position,r in enumerate(batch,1):manifest.append({'batch':number,'position':position,'图片':r['filename'],'split':r['split'],'source_video':r['meta']['source_video'],'source_frame_idx':r['meta']['source_frame_idx'],'eye':r['meta']['eye']})
    with (out/'manifest.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(manifest[0]));writer.writeheader();writer.writerows(manifest)
    write_json(HERE/'before/inventory.json',original);write_json(HERE/'after-reset-inventory.json',after)
    # Catch non-cooperating external label editors as well as protecting Qt saves.
    for r in after:
        assert helpers.digest(Path(r['label_path']).read_bytes())==r['label_sha256'],r['filename']
    replacement=helpers.csv_update(parsed,updates);helpers.atomic_replace(path,replacement,raw)
    result={'dataset':str(root),'rows':len(rows),'label_pending':len(rows),'scene_pending':len(rows),'batch_sizes':[len(b) for b in batches],'metadata_before_sha256':helpers.digest(raw),'metadata_after_sha256':helpers.digest(replacement),'metadata_backup':str(HERE/'before/metadata.csv'),'images_written':0,'labels_written':0,'created_at_utc':datetime.now(timezone.utc).isoformat()}
    write_json(HERE/'reset-result.json',result);print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
