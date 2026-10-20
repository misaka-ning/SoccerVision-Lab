#!/usr/bin/env python3
"""Read-only source audit; all generated artifacts stay under the audit output."""
import os
from pathlib import Path

ROOT = Path('/home/misaka/workspace')
OUT = ROOT / 'dataset_processing/dataset-audit-20261019'
SAFE = OUT / 'safety'
for k in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[k] = '1'
os.environ['YOLO_CONFIG_DIR'] = str(SAFE / 'ultralytics-config')
os.environ['MPLCONFIGDIR'] = str(SAFE / 'matplotlib-config')
os.environ['YOLO_AUTOINSTALL'] = 'false'
os.environ['WANDB_DISABLED'] = 'true'

import argparse
import csv
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import random
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from types import SimpleNamespace

DATA = ROOT / 'datasets'
SEED = 20261019
FLAGS = ['Small', 'Occluded', 'Blurred', 'No Ball']
EXPECTED = {
    'metadata.csv': 'cb2386ef97c2f864cad27adf8fc06dc6fc74cea2caf828f32a685abc05985ef9',
    'dataset.yaml': '7781d543cc43364f2a2598ff596adb05a8e80b4547af40195665565a8eef05b6',
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_json(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def guard():
    values = {name: sha(DATA / name) for name in EXPECTED}
    assert values == EXPECTED, values
    return values


def resolve_source(path):
    p = Path(path)
    if p.exists():
        return p
    rel = p.relative_to(DATA)
    archived = DATA / 'excluded' / rel
    if archived.exists():
        return archived
    raise FileNotFoundError(str(p))


def records():
    rows = list(csv.DictReader((DATA / 'metadata.csv').open(encoding='utf-8-sig', newline='')))
    for r in rows:
        r['filename'] = r['图片']
        r['path'] = str(DATA / 'images' / r['split'] / r['filename'])
        r['label_path'] = str(DATA / 'labels' / r['split'] / (Path(r['filename']).stem + '.txt'))
        r['current_path'] = str(resolve_source(r['path']))
        r['current_label_path'] = str(resolve_source(r['label_path']))
        r['label_text'] = Path(r['current_label_path']).read_text()
        r['boxes'] = [list(map(float, x.split())) for x in r['label_text'].splitlines() if x.strip()]
        r['usable'] = r['annotation_status'] in ('reviewed_annotation', 'negative_confirmed') and r['label_review_required'] == r['scene_review_required'] == '0'
        # Ignore <=1e-6 normalized serialization-rounding excess at exact image edges.
        r['geometry_invalid'] = any(len(b) != 5 or any(not math.isfinite(z) for z in b) or b[0] != 0 or b[3] <= 0 or b[4] <= 0 or b[1] - b[3]/2 < -1e-6 or b[1] + b[3]/2 > 1+1e-6 or b[2] - b[4]/2 < -1e-6 or b[2] + b[4]/2 > 1+1e-6 for b in r['boxes'])
    return rows


def safe_cache_header(p):
    """Read only NPY metadata, never unpickle existing cache payloads."""
    import numpy.lib.format as fmt
    st = p.stat()
    result = {'path': str(p), 'size': st.st_size, 'mtime_ns': st.st_mtime_ns, 'mtime_utc': datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(), 'sha256': sha(p), 'payload_loaded': False}
    try:
        with p.open('rb') as f:
            version = fmt.read_magic(f)
            shape, fortran, dtype = fmt._read_array_header(f, version)
        result.update(npy_version=list(version), shape=list(shape), fortran_order=fortran, dtype=str(dtype), contains_object=dtype.hasobject)
    except Exception as e:
        result['header_error'] = str(e)
    return result


def safety(rows):
    SAFE.mkdir(parents=True, exist_ok=True)
    for k in ['ultralytics-config', 'matplotlib-config']:
        (SAFE / k).mkdir(exist_ok=True)
    import torch
    torch.set_num_threads(1)
    import ultralytics
    from ultralytics.data.base import BaseDataset
    from ultralytics.data.utils import verify_image_label, get_hash
    discovered = {}
    for split in ['train', 'val', 'test']:
        # Calling discovery alone does not construct a dataset, build caches, or decode/repair images.
        discovered[split] = BaseDataset.get_img_files(SimpleNamespace(prefix='AUDIT discovery: ', fraction=1.0), str(DATA / 'images' / split))
    lookup = {r['path']: r for r in rows}
    raw_counts = {}
    for split, paths in discovered.items():
        rr = [lookup[p] for p in paths]
        ex = [r for r in rr if not r['usable']]
        raw_counts[split] = {'discovered': len(paths), 'usable': sum(r['usable'] for r in rr), 'excluded_discovered': len(ex), 'excluded_empty': sum(not r['boxes'] for r in ex), 'excluded_nonempty': sum(bool(r['boxes']) for r in ex), 'excluded_geometry_invalid': sum(r['geometry_invalid'] for r in ex)}
    caches, symlinks = [], []
    for parent in [DATA, ROOT/'script/model-training', ROOT/'baseline', ROOT/'experiments']:
        if not parent.exists():
            continue
        for base, dirs, files in os.walk(parent):
            for name in dirs + files:
                p = Path(base)/name
                if p.is_symlink():
                    symlinks.append({'path': str(p), 'target': os.readlink(p), 'resolved': str(p.resolve())})
                if p.is_file() and p.suffix.lower() == '.cache':
                    caches.append(safe_cache_header(p))
    inode_groups, real_groups = defaultdict(list), defaultdict(list)
    for split, paths in discovered.items():
        for f in paths:
            st = Path(f).stat()
            inode_groups[(st.st_dev, st.st_ino)].append({'split': split, 'path': f})
            real_groups[str(Path(f).resolve())].append({'split': split, 'path': f})
    # Isolated physical copies ensure even Ultralytics JPEG repair cannot modify an original file.
    tests = []
    invalid = [r for r in rows if r['geometry_invalid']]
    smoke = invalid + [next(r for r in rows if not r['usable'] and not r['boxes'])]
    for i, r in enumerate(smoke):
        d = SAFE/'verify-copies'/str(i)
        d.mkdir(parents=True, exist_ok=True)
        im, lb = d/r['filename'], d/(Path(r['filename']).stem+'.txt')
        shutil.copyfile(r['current_path'], im)
        shutil.copyfile(r['current_label_path'], lb)
        result = verify_image_label((str(im), str(lb), 'AUDIT isolated: ', False, 1, 0, 0, False))
        tests.append({'source_image': r['path'], 'source_label': r['label_path'], 'current_source_image': r['current_path'], 'current_source_label': r['current_label_path'], 'source_label_text': r['label_text'], 'source_geometry_invalid': r['geometry_invalid'], 'physical_copy_image': str(im), 'physical_copy_label': str(lb), 'accepted': result[0] is not None, 'returned_box_count': len(result[1]) if result[1] is not None else None, 'counters': dict(zip(['missing','found','empty','corrupt'], result[5:9])), 'message': result[9], 'copied_label_unchanged': sha(lb)==sha(r['current_label_path'])})
    # A disposable filtered view is only for discovery validation. No YOLODataset/YOLO()/train is called.
    view = SAFE/'filtered-view'
    for split in ['train', 'val', 'test']:
        (view/'images'/split).mkdir(parents=True, exist_ok=True)
        (view/'labels'/split).mkdir(parents=True, exist_ok=True)
    selected = [r for r in rows if r['usable']]
    for r in selected:
        ip = view/'images'/r['split']/r['filename']
        if not ip.exists():
            ip.symlink_to(r['path'])
        lp = view/'labels'/r['split']/(Path(r['filename']).stem+'.txt')
        shutil.copyfile(r['label_path'], lp)
    (view/'dataset.yaml').write_text(f'path: {view}\ntrain: images/train\nval: images/val\ntest: images/test\nnc: 1\nnames:\n  0: football\n')
    view_counts = {}
    for split in ['train', 'val', 'test']:
        files = BaseDataset.get_img_files(SimpleNamespace(prefix='AUDIT view discovery: ', fraction=1.0), str(view/'images'/split))
        forbidden = [f for f in files if not lookup[str(Path(f).resolve())]['usable']]
        view_counts[split] = {'discovered': len(files), 'excluded': len(forbidden)}
        assert not forbidden
    # Demonstrate hash invalidation behavior only on a harmless audit text file.
    test = SAFE/'hash-probe.txt'
    test.write_text('0 0.5 0.5 0.1 0.1\n')
    h0, t0 = get_hash([str(test)]), test.stat()
    test.write_text('0 0.6 0.5 0.1 0.1\n')
    os.utime(test, ns=(t0.st_atime_ns, t0.st_mtime_ns+1000000))
    h1 = get_hash([str(test)])
    os.utime(test, ns=(t0.st_atime_ns, t0.st_mtime_ns))
    h2 = get_hash([str(test)])
    # Static source excerpts and hashes make version-dependent claims reproducible.
    pkg = Path(importlib.util.find_spec('ultralytics').origin).parent
    source_specs = {'data/base.py': [(189,226)], 'data/dataset.py': [(118,186),(200,216),(271,324)], 'data/utils.py': [(225,240),(432,500),(959,998)], 'models/yolo/detect/train.py': [(130,146),(183,201)]}
    source_manifest = []
    for rel, ranges in source_specs.items():
        src = pkg/rel
        lines = src.read_text().splitlines()
        dest = SAFE/'source-excerpts'/rel.replace('/','_')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text('\n\n'.join('\n'.join(f'{i}: {lines[i-1]}' for i in range(a,min(b,len(lines))+1)) for a,b in ranges)+'\n')
        source_manifest.append({'source': str(src), 'sha256': sha(src), 'excerpt': str(dest), 'line_ranges': ranges})
    report = {'performed_at_utc': datetime.now(timezone.utc).isoformat(), 'environment': {'python': os.sys.version, 'ultralytics': ultralytics.__version__, 'torch': torch.__version__, 'torch_threads': torch.get_num_threads(), 'numpy': importlib.metadata.version('numpy'), 'YOLO_CONFIG_DIR': os.environ['YOLO_CONFIG_DIR']}, 'source_sha256': guard(), 'raw_loader_discovery': raw_counts, 'cache_inventory': caches, 'cache_payloads_unpickled': 0, 'symlinks': symlinks, 'duplicate_real_paths': [v for v in real_groups.values() if len(v)>1], 'duplicate_inode_paths': [v for v in inode_groups.values() if len(v)>1], 'class_id_counts': dict(Counter(str(int(b[0])) for r in rows for b in r['boxes'])), 'isolated_verify_cases': tests, 'filtered_view': {'path': str(view), 'discovery_only': True, 'full_YOLODataset_not_constructed': True, 'counts': view_counts, 'total': len(selected), 'excluded': 0, 'label_copies': len(selected), 'image_symlinks': len(selected), 'warning': 'Only an audit discovery view; original YAML unchanged. Training compatibility, augmentation, and batches were not exercised; do not treat as approved experimental split.'}, 'cache_hash_probe': {'same_length_changed_mtime_invalidates': h0!=h1, 'same_size_same_mtime_content_change_can_collide': h0==h2}, 'source_excerpts': source_manifest, 'model_instantiated': False, 'training_executed': False, 'model_or_engine_written': False, 'downloads_requested': False, 'source_cache_written': False}
    relocated = [r for r in rows if r['path'] != r['current_path']]
    report['phase'] = 'post_isolation' if relocated else 'pre_isolation'
    report['metadata_record_count'] = len(rows)
    report['archived_excluded_count'] = len(relocated)
    report['archive_by_split'] = dict(Counter(r['split'] for r in relocated))
    report['active_class_id_counts'] = dict(Counter(str(int(b[0])) for r in rows if r['usable'] for b in r['boxes']))
    report['active_geometry_invalid'] = sum(r['geometry_invalid'] for r in rows if r['usable'])
    assert all(t['accepted'] for t in tests)
    write_json(SAFE/'training-safety.json', report)
    return report


def sample(rows):
    from PIL import Image, ImageDraw
    rng = random.Random(SEED)
    used, draws = set(), []
    defs = [('ordinary', lambda r:r['usable'] and r['boxes'] and all(r[f]=='0' for f in FLAGS)), ('Small', lambda r:r['usable'] and r['Small']=='1' and bool(r['boxes'])), ('Occluded', lambda r:r['usable'] and r['Occluded']=='1' and bool(r['boxes'])), ('Blurred', lambda r:r['usable'] and r['Blurred']=='1' and bool(r['boxes'])), ('No Ball', lambda r:r['usable'] and r['No Ball']=='1'), ('multi_ball', lambda r:r['usable'] and len(r['boxes'])>1), ('Small+Occluded',lambda r:r['usable'] and r['Small']==r['Occluded']=='1' and bool(r['boxes'])), ('Small+Blurred',lambda r:r['usable'] and r['Small']==r['Blurred']=='1' and bool(r['boxes']))]
    for name, predicate in defs:
        eligible = [r for r in rows if predicate(r)]
        quotas = {'train':3,'val':2,'test':2} if name!='multi_ball' else {'train':7,'val':0,'test':0}
        picks = []
        for split, quota in quotas.items():
            pool = sorted([r for r in eligible if r['split']==split and r['path'] not in used], key=lambda r:r['path'])
            picked = rng.sample(pool, min(quota,len(pool)))
            for r in picked:
                used.add(r['path']);picks.append(r)
                draws.append((r,name,f'seed={SEED}; sequential without replacement; stratum={name}; split={split}; draw={len(picked)}/{len(pool)} remaining eligible'))
        pool = sorted([r for r in eligible if r['path'] not in used], key=lambda r:r['path'])
        for r in rng.sample(pool,min(7-len(picks),len(pool))):
            used.add(r['path']);draws.append((r,name,f'seed={SEED}; sequential without replacement; stratum={name}; split quota shortage backfill from {len(pool)} remaining'))
    excluded_defs = [('excluded_invalid',lambda r:not r['usable'] and r['geometry_invalid'] and r['split']=='train',1), ('excluded_empty',lambda r:not r['usable'] and not r['boxes'] and r['split']=='train',3), ('excluded_nonempty',lambda r:not r['usable'] and bool(r['boxes']) and not r['geometry_invalid'] and r['split']=='train',2), ('excluded_val',lambda r:not r['usable'] and r['split']=='val',1), ('excluded_test',lambda r:not r['usable'] and r['split']=='test',1)]
    for name,pred,k in excluded_defs:
        pool=sorted([r for r in rows if pred(r) and r['path'] not in used],key=lambda r:r['path'])
        for r in rng.sample(pool,min(k,len(pool))):
            used.add(r['path']);draws.append((r,'excluded',f'seed={SEED}; excluded substratum={name}; uniform without replacement draw={min(k,len(pool))}/{len(pool)}'))
    assert len(draws)==len(used)==64
    out=[]
    for i,(r,stratum,method) in enumerate(draws):
        out.append({'sample_id':f'S{i:03d}','filename':r['filename'],'path':r['path'],'split':r['split'],'label_path':r['label_path'],'source_current_image_path':r['current_path'],'source_current_label_path':r['current_label_path'],'original_label_text':r['label_text'],**{f:r[f] for f in FLAGS},'annotation_status':r['annotation_status'],'stratum':stratum,'seed':SEED,'sample_probability':'','sampling_method':method,'issue':'','severity':'','requires_review':'','review_result':'','assistant_observation':'','assistant_visual_seen':False,'page':str(OUT/'samples'/f'page-{i//2:03d}.png')})
    (OUT/'samples').mkdir(exist_ok=True)
    for start in range(0,len(out),2):
        cards=[]
        for i in range(start,min(start+2,len(out))):
            rec=out[i];r=draws[i][0];im=Image.open(r['current_path']).convert('RGB');w,h=im.size
            # Keep 672px originals native. For larger originals, retain full native pixels on separate cards.
            card=Image.new('RGB',(max(w,900),h+62),'#202020');card.paste(im,(0,62));d=ImageDraw.Draw(card)
            title=f"{rec['sample_id']} {r['filename']} {r['split']} {w}x{h} b={len(r['boxes'])} {rec['stratum']}"
            d.text((3,3),title,fill='white');d.text((3,21),f"S={r['Small']} O={r['Occluded']} B={r['Blurred']} N={r['No Ball']} status={r['annotation_status']}",fill='white');d.text((3,39),'Red: original label. review_result remains empty; assistant notes are separate.',fill='white')
            for j,b in enumerate(r['boxes']):
                _,cx,cy,bw,bh=b;xy=[(cx-bw/2)*w,62+(cy-bh/2)*h,(cx+bw/2)*w,62+(cy+bh/2)*h]
                d.rectangle(xy,outline='#ff3333',width=2);d.text((max(0,xy[0]),max(62,xy[1]-11)),f'b{j}',fill='#ff3333')
            cards.append(card)
        page=Image.new('RGB',(max(c.width for c in cards),sum(c.height for c in cards)+5),'#202020');y=0
        for c in cards:page.paste(c,(0,y));y+=c.height+5
        page.save(out[start]['page'])
    write_json(OUT/'data/visual-findings.json',{'seed':SEED,'method':'Nine strata, sequential split quotas without replacement; 7 per usable stratum and 8 excluded; explicit draw method per row. Not prevalence-weighted. Review results intentionally empty.','selected_count':len(out),'actual_opened_pages':[],'records':out})
    write_manifest(out)
    print('visual sample',len(out),'pages',len(out)//2,Counter(r['split'] for r in out))


def write_manifest(rows):
    p=OUT/'data/visual_sample_manifest.csv'
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['safety','sample','all'],default='all');args=parser.parse_args()
    guard();rr=records()
    if args.phase in ['safety','all']:print(json.dumps(safety(rr),ensure_ascii=False,indent=2))
    if args.phase in ['sample','all']:sample(rr)
    guard()
