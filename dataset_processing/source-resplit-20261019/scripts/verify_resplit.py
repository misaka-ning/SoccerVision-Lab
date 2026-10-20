#!/usr/bin/env python3
"""Independent, read-only validation of the current source-based partition."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'): os.environ[k]='1'
try: os.nice(10)
except OSError: pass
import csv, hashlib, importlib.metadata, json, re, stat
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

OUT=Path(__file__).resolve().parents[1]
D=Path('/home/misaka/workspace/datasets')
VALID=OUT/'validation'; VALID.mkdir(exist_ok=True)
os.environ['YOLO_CONFIG_DIR']=str(VALID/'ultralytics-config')
os.environ['MPLCONFIGDIR']=str(VALID/'matplotlib-config')
for p in (Path(os.environ['YOLO_CONFIG_DIR'])/'Ultralytics',Path(os.environ['MPLCONFIGDIR'])):
    p.mkdir(parents=True,exist_ok=True)
def load(p): return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()
def filename_source(name):
    if re.fullmatch(r'frame_\d+_(?:left|right)\.png',name): return '10:47:48','val'
    if name.startswith('rec_20261013_181326_'): return '18:13:26','val'
    if name.startswith('video_4bec9c343db72928_frame_'): return '18:15:31','train'
    if name.startswith('legacy_'): return 'legacy','train'
    raise AssertionError('Unexpected source filename: '+name)

def main():
    plan=load(OUT/'plan.json'); result=load(OUT/'result.json')
    before=rows(OUT/'before/metadata.csv'); after=rows(D/'metadata.csv')
    assert [r['图片'] for r in before]==[r['图片'] for r in after]
    assert len(before)==len(after)==8398 and len({r['图片'] for r in after})==8398
    grouped=defaultdict(Counter); stats=defaultdict(Counter); checks=Counter()
    expected=defaultdict(set)
    for a,b,p in zip(before,after,plan['records']):
        assert all(a[k]==b[k] for k in a if k!='split')
        source,target=filename_source(b['图片'])
        ex=b['annotation_status']=='reviewed_excluded'
        if ex: assert a==b
        else: assert b['split']==target
        grouped[source]['all']+=1; grouped[source]['excluded' if ex else 'usable']+=1
        for kind,key in [('images','image_sha256'),('labels','label_sha256')]:
            suffix=b['图片'] if kind=='images' else Path(b['图片']).stem+'.txt'
            base=D/'excluded' if ex else D
            path=base/kind/b['split']/suffix
            assert path.is_file() and not path.is_symlink()
            assert sha(path)==p['files'][kind]['sha256']
            assert stat.S_IMODE(path.stat().st_mode)==p['files'][kind]['mode']
            checks[kind]+=1
            if not ex: expected[kind,b['split']].add(str(path))
        if not ex:
            s=stats[b['split']]; s['images']+=1
            label=Path(p['files']['labels']['after']).read_text(encoding='utf-8-sig')
            n=sum(bool(line.strip()) for line in label.splitlines())
            assert bool(n)==(b['No Ball']=='0')
            s['positive_images' if n else 'negative_images']+=1; s['boxes']+=n
            for f in ['Small','Occluded','Blurred','No Ball']: s[f]+=int(b[f])
        checks['metadata_changed_rows']+=int(a!=b)
    assert dict(grouped['10:47:48'])=={'all':1176,'usable':1154,'excluded':22}
    assert dict(grouped['18:13:26'])=={'all':70,'usable':69,'excluded':1}
    assert dict(grouped['18:15:31'])=={'all':6438,'usable':6212,'excluded':226}
    assert dict(grouped['legacy'])=={'all':714,'usable':713,'excluded':1}
    assert checks=={'images':8398,'labels':8398,'metadata_changed_rows':1185}
    for kind in ('images','labels'):
        for split in ('train','val','test'):
            paths={str(p) for p in (D/kind/split).iterdir()}
            assert paths==expected[kind,split],f'Unexpected files including temporary locks: {kind}/{split}'
    assert stats['train']['images']==6925 and stats['val']['images']==1223
    assert not list((D/'images/test').iterdir()) and not list((D/'labels/test').iterdir())
    for p,expected_sha in plan['archive_reference_sha256'].items(): assert sha(Path(p))==expected_sha
    for c in plan['configs']: assert sha(Path(c['path']))==c['sha256_after']
    for m in plan['moves']:
        assert not Path(m['source']).exists()
        assert sha(Path(m['backup']))==m['sha256']==sha(Path(m['destination']))
    assert not list(D.rglob('*.review.lock')) and not list(D.rglob('*.cache'))
    import yaml
    config=yaml.safe_load((D/'dataset.yaml').read_text())
    assert config['path']==str(D) and config['nc']==1 and config['names']=={0:'football'}
    from ultralytics.data.base import BaseDataset
    from ultralytics.data.utils import img2label_paths
    from ultralytics.utils import USER_CONFIG_DIR
    assert Path(USER_CONFIG_DIR).is_relative_to(VALID),str(USER_CONFIG_DIR)
    loader={}
    for split,n in [('train',6925),('val',1223)]:
        files=BaseDataset.get_img_files(SimpleNamespace(prefix='SPLIT validation: ',fraction=1.0),str(D/config[split]))
        assert len(files)==n and set(files)==expected['images',split]
        assert set(img2label_paths(files))==expected['labels',split]
        loader[split]=dict(images=len(files),all_labels_present=True,excluded_discovered=0)
    try:
        BaseDataset.get_img_files(SimpleNamespace(prefix='Empty Test expected: ',fraction=1.0),str(D/config['test']))
    except FileNotFoundError as e:
        loader['test']=dict(images=0,expected_empty=True,discovery_raises='FileNotFoundError',message=str(e))
    else: raise AssertionError('Empty Test should not be treated as a populated evaluation dataset')
    assert not list(D.rglob('*.cache'))
    output=dict(status='PASS',verified_at_utc=datetime.now(timezone.utc).isoformat(),
        method='Independent stdlib CSV parse, filename grouping (not reuse of migration source matcher), full SHA8398images+8398labels,2370 backup/destination checks, exact path sets and actual Ultralytics file discovery only.',
        checked=dict(checks),sources={k:dict(v) for k,v in grouped.items()},active_statistics={k:dict(v) for k,v in stats.items()},
        loader=loader,ultralytics_version=importlib.metadata.version('ultralytics'),
        metadata_sha256=sha(D/'metadata.csv'),yaml_sha256=sha(D/'dataset.yaml'),
        archive250_unchanged=True,all_metadata_fields_except_split_unchanged=True,
        no_source_caches_or_locks_left=True,model_instantiated=False,training_executed=False,
        canonical_label_cache_written=False,ultralytics_runtime_settings_redirected=True,validation_runtime_config_directory=str(USER_CONFIG_DIR),
        script_sha256=sha(Path(__file__)))
    (OUT/'verification.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    with (OUT/'split_distribution.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['split','images','positive_images','negative_images','boxes','Small','Occluded','Blurred','No Ball']
        writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader()
        for split in ('train','val','test'): writer.writerow(dict.fromkeys(fields,0)|dict(stats[split])|{'split':split})
    print(json.dumps(dict(status='PASS',counts=dict(checks),statistics=output['active_statistics'],test_images=0),ensure_ascii=False))

if __name__=='__main__': main()
