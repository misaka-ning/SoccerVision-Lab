#!/usr/bin/env python3
"""Read-only, one-process image/YOLO inventory. All outputs stay in OUT.

No training, inference, label repair, source metadata rewrite, or source cache.
"""
import os
for _k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_k] = '1'
import csv, hashlib, io, json, math, platform, re, struct, sys, time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, __version__ as PIL_VERSION

BASE=Path('/home/misaka/workspace')
DATA=BASE/'datasets'
OUT=BASE/'dataset_processing/dataset-audit-20261019'
SNAPSHOT=OUT/'data/source-metadata.csv'
POLICY=BASE/'dataset_processing/batch-review-20261016/review-policy.json'
REPORT=BASE/'dataset_processing/batch-review-20261016/final-statistics-20261019/REPORT.md'
FLAGS=('Small','Occluded','Blurred','No Ball')
EPS=1e-6
cv2.setNumThreads(1)
cv2.ocl.setUseOpenCL(False)
try: os.nice(10)
except OSError: pass

def now(): return datetime.now(timezone.utc).isoformat()
def sha(raw): return hashlib.sha256(raw).hexdigest()
def file_sha(p): return sha(p.read_bytes()) if p.exists() else None
def json_write(p,obj):
    with p.open('w',encoding='utf-8') as f: json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False)
def csv_write(p,fields,rows):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)
def pack_bits(a):
    v=0
    for b in a.reshape(-1): v=(v<<1)|int(b)
    return f'{v:016x}'
def groups(records,key):
    d=defaultdict(list)
    for r in records:
        if r.get(key) is not None: d[r[key]].append(r['index'])
    return [v for v in d.values() if len(v)>1]
def iou(a,b):
    x=max(0,min(a[2],b[2])-max(a[0],b[0])); y=max(0,min(a[3],b[3])-max(a[1],b[1]))
    intersection=x*y
    union=max(0,a[2]-a[0])*max(0,a[3]-a[1])+max(0,b[2]-b[0])*max(0,b[3]-b[1])-intersection
    return intersection/union if union>0 else 0

def parse_labels(raw):
    errors=[]; boxes=[]
    try: text=raw.decode('utf-8-sig')
    except UnicodeDecodeError as e: return [],[f'encoding:{e}']
    for n,line in enumerate(text.splitlines(),1):
        if not line.strip(): continue
        fields=line.split()
        if len(fields)!=5:
            errors.append(f'line {n}: expected 5 tokens; got {len(fields)}'); continue
        try: vals=[float(v) for v in fields]
        except ValueError:
            errors.append(f'line {n}: nonnumeric token'); continue
        if not all(math.isfinite(v) for v in vals):
            errors.append(f'line {n}: NaN or Inf'); continue
        c,x,y,w,h=vals; local=[]
        if not c.is_integer() or c!=0: local.append(f'class_id={c:g}, expected integer 0')
        if w<=0 or h<=0: local.append('nonpositive width or height')
        if any(v < -EPS or v > 1+EPS for v in (x,y,w,h)): local.append('xywhn outside [0,1]')
        xyxy=[x-w/2,y-h/2,x+w/2,y+h/2]
        if any(v < -EPS or v > 1+EPS for v in xyxy): local.append('bbox corners outside [0,1]')
        for e in local: errors.append(f'line {n}: {e}')
        boxes.append({'class_id':int(c) if c.is_integer() else c,'xywhn':[x,y,w,h],
                      'xyxy':xyxy,'valid':not local,'line':n})
    return boxes,errors

def issue(r,kind,severity,evidence,recommendation,review=True):
    return {'image_path':r.get('image_path',''),'label_path':r.get('label_path',''),
            'split':r.get('split',''),'status':r.get('meta',{}).get('annotation_status',''),
            'issue_type':kind,'severity':severity,'evidence':evidence,
            'recommendation':recommendation,'requires_review':str(bool(review)).lower(),'review_result':''}

def main():
    started=now(); t=time.monotonic()
    for d in ('data','logs','scripts'): (OUT/d).mkdir(parents=True,exist_ok=True)
    originals={str(p):file_sha(p) for p in (DATA/'metadata.csv',DATA/'dataset.yaml',SNAPSHOT,POLICY,REPORT)}
    policy=json.loads(POLICY.read_text(encoding='utf-8'))
    with SNAPSHOT.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    if originals[str(SNAPSHOT)] != originals[str(DATA/'metadata.csv')]: raise RuntimeError('metadata snapshot differs from canonical')
    gray_stack=np.zeros((len(rows),72,128),dtype=np.uint8)
    records=[]; issues=[]; expected_images=set(); expected_labels=set()
    image_inode=defaultdict(list); label_inode=defaultdict(list); warnings_seen=[]
    for idx,row in enumerate(rows):
        name=row['图片']; split=row['split']
        ip=DATA/'images'/split/name; lp=DATA/'labels'/split/(Path(name).stem+'.txt')
        expected_images.add(str(ip)); expected_labels.add(str(lp))
        r={'index':idx,'filename':name,'split':split,'image_path':str(ip),'label_path':str(lp),
           'meta':row,'width':None,'height':None,'image_sha256':None,'label_sha256':None,'pixel_sha256':None,
           'phash':None,'dhash':None,'usable':False,'image_valid':False,'label_valid':False,'boxes':[],
           'label_errors':[],'image_errors':[],'grey_mean':None,'grey_std':None,'grey_entropy':None,
           'black_ratio':None,'white_ratio':None,'blank_candidate':False,
           'source_video':row.get('source_video',''),'source_frame_idx':row.get('source_frame_idx',''),'eye':row.get('eye','')}
        if Path(name).name!=name or split not in ('train','val','test'):
            r['image_errors'].append('metadata filename contains path or unexpected split')
        if ip.is_symlink(): issues.append(issue(r,'image_symlink','warning',str(ip.resolve()),'人工核实符号链接的来源及稳定性'))
        if lp.is_symlink(): issues.append(issue(r,'label_symlink','warning',str(lp.resolve()),'人工核实符号链接的来源及稳定性'))
        try:
            st=ip.stat(); image_inode[(st.st_dev,st.st_ino)].append(idx)
            raw=ip.read_bytes(); r['image_sha256']=sha(raw)
            with Image.open(io.BytesIO(raw)) as im:
                im.load()  # Complete decompression; verify() alone is deliberately not used.
                r['width'],r['height']=im.size; r['format']=im.format; r['mode']=im.mode
                rgb=np.asarray(im.convert('RGB'),dtype=np.uint8)
            h,w=rgb.shape[:2]
            if min(h,w)<=0: raise ValueError('nonpositive dimensions')
            r['pixel_sha256']=sha(struct.pack('>II',w,h)+rgb.tobytes(order='C'))
            gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
            small=cv2.resize(gray,(32,32),interpolation=cv2.INTER_AREA)
            dct=cv2.dct(small.astype(np.float32))[:8,:8]
            r['phash']=pack_bits(dct > np.median(dct.reshape(-1)[1:]))
            g9=cv2.resize(gray,(9,8),interpolation=cv2.INTER_AREA)
            r['dhash']=pack_bits(g9[:,1:] > g9[:,:-1])
            gray_stack[idx]=cv2.resize(gray,(128,72),interpolation=cv2.INTER_AREA)
            hist=np.bincount(gray.reshape(-1),minlength=256).astype(np.float64); prob=hist[hist>0]/gray.size
            r['grey_mean']=float(gray.mean()); r['grey_std']=float(gray.std())
            r['grey_entropy']=float(-(prob*np.log2(prob)).sum())
            r['black_ratio']=float((gray<=5).mean()); r['white_ratio']=float((gray>=250).mean())
            r['blank_candidate']=bool(r['grey_std']<2 or r['grey_entropy']<0.5 or max(r['black_ratio'],r['white_ratio'])>.99)
            r['image_valid']=not r['image_errors']
            ext=ip.suffix.lower(); expected_fmt={'PNG':{'.png'},'JPEG':{'.jpg','.jpeg'}}
            if r['format'] in expected_fmt and ext not in expected_fmt[r['format']]:
                issues.append(issue(r,'extension_format_mismatch','warning',f'extension={ext}; actual={r["format"]}','复核文件名后缀与真实编码'))
            if min(h,w)<32 or max(h,w)>16384:
                issues.append(issue(r,'unusual_dimensions','warning',f'{w}x{h}','复核图像尺寸与使用场景'))
            if r['blank_candidate']:
                issues.append(issue(r,'blank_black_white_candidate','warning',f'mean={r["grey_mean"]:.3f}; std={r["grey_std"]:.3f}; entropy={r["grey_entropy"]:.3f}; black={r["black_ratio"]:.6f}; white={r["white_ratio"]:.6f}','人工查看完整图像；统计阈值只能筛查，不能自动认定无效或无球'))
        except Exception as e:
            r['image_errors'].append(f'{type(e).__name__}: {e}'); r['image_valid']=False
        try:
            st=lp.stat(); label_inode[(st.st_dev,st.st_ino)].append(idx)
            raw=lp.read_bytes(); r['label_sha256']=sha(raw)
            r['boxes'],r['label_errors']=parse_labels(raw); r['label_valid']=not r['label_errors']
        except Exception as e: r['label_errors'].append(f'{type(e).__name__}: {e}')
        valid_boxes=[b for b in r['boxes'] if b['valid']]
        r['valid_box_count']=len(valid_boxes); r['box_count']=len(r['boxes'])
        double=row.get('scene_review_required')==row.get('label_review_required')=='0'
        status=row.get('annotation_status'); nb=row.get('No Ball')
        positive=(status=='reviewed_annotation' and len(valid_boxes)>0 and nb=='0')
        negative=(status=='negative_confirmed' and len(valid_boxes)==0 and nb=='1')
        r['usable']=bool(double and r['image_valid'] and r['label_valid'] and (positive or negative))
        for e in r['image_errors']: issues.append(issue(r,'image_decode_or_path_error','error',e,'保留原文件并人工核实损坏或缺失来源'))
        for e in r['label_errors']: issues.append(issue(r,'label_format_or_geometry','error',e,'保留原label；已排除样本继续隔离，重新标注后须复审'))
        for k in FLAGS:
            if row.get(k) not in ('0','1'): issues.append(issue(r,'invalid_scene_flag','error',f'{k}={row.get(k)!r}','按项目四场景口径人工复核'))
        if not double: issues.append(issue(r,'review_incomplete','error',f'label={row.get("label_review_required")}; scene={row.get("scene_review_required")}','完成双项审核后再纳入可用数据'))
        if status!='reviewed_excluded' and not (positive or negative):
            issues.append(issue(r,'status_NoBall_label_mismatch','error',f'status={status}; No Ball={nb}; valid_boxes={len(valid_boxes)}','按最终人工确认的球框和No Ball状态复核'))
        if status=='reviewed_excluded':
            issues.append(issue(r,'excluded_in_raw_training_directory','high',f'status=reviewed_excluded; valid_boxes={len(valid_boxes)}; dataset.yaml uses images/{split}','训练/验证/测试入口必须按审核状态过滤；空label不能自动视为确认负例',False))
        scale=672/max(r['width'] or 1,r['height'] or 1)
        for b in valid_boxes:
            _,_,bw,bh=b['xywhn']; pxw=bw*(r['width'] or 0); pxh=bh*(r['height'] or 0)
            b['width_px']=pxw; b['height_px']=pxh; b['width_at_672']=pxw*scale; b['height_at_672']=pxh*scale
            b['long_side_at_672']=max(pxw,pxh)*scale; b['area_fraction']=bw*bh
            if min(pxw,pxh)<2 or pxw*pxh<4:
                issues.append(issue(r,'tiny_bbox_candidate','warning',f'line={b["line"]}; px={pxw:.3f}x{pxh:.3f}; area={pxw*pxh:.3f}','人工放大复核；极小目标可能真实存在，不能自动删除'))
        for a in range(len(valid_boxes)):
            for b in range(a+1,len(valid_boxes)):
                ov=iou(valid_boxes[a]['xyxy'],valid_boxes[b]['xyxy'])
                if ov>=.9: issues.append(issue(r,'duplicate_high_IoU_boxes','warning',f'lines={valid_boxes[a]["line"]},{valid_boxes[b]["line"]}; IoU={ov:.6f}','复核是否同一足球被重复框选；不自动删框'))
        # Scene tags are project definitions, not detector classes or automatic ground truth.
        # Thresholds are deliberately separated from the ~40px project boundary.
        lengths=[b['long_side_at_672'] for b in valid_boxes]
        if lengths and row.get('Occluded')=='0':
            if row.get('Small')=='1' and max(lengths)>50:
                issues.append(issue(r,'Small_large_box_risk','candidate',f'long sides at672={lengths}; >50px risk band; Occluded=0','查看完整足球及上下文；项目Small约40px口径，只是风险候选，不可用残片尺寸定错'))
            if row.get('Small')=='0' and max(lengths)<30:
                issues.append(issue(r,'Small_small_box_risk','candidate',f'long sides at672={lengths}; all<30px risk band; Occluded=0','查看完整足球及上下文；项目Small约40px口径，只是风险候选'))
        if lengths and row.get('Occluded')=='0':
            if any(min(b['xyxy'])<.002 or max(b['xyxy'])>.998 for b in valid_boxes):
                issues.append(issue(r,'Occluded_boundary_quality_candidate','candidate','球框有归一化边界距图像边缘<0.002；仅近边筛查，未判定球体截断','人工查看球体是否被边缘实际截断；贴近但完整不算遮挡'))
        # auto/preserved counts are historical values; never treated as current correctness.
        for historical in ('auto_box_count','preserved_box_count'):
            try: old=int(row.get(historical,''))
            except (ValueError,TypeError): continue
            if old!=len(r['boxes']):
                issues.append(issue(r,'historical_box_count_difference','info',f'{historical}={old}; current_parsed_boxes={len(r["boxes"])}','历史自动/保留计数可能早于最终人工审核；仅作追溯，不据此判标注错误',False))
        records.append(r)
        if (idx+1)%500==0 or idx+1==len(rows):
            print(json.dumps({'decoded':idx+1,'total':len(rows),'elapsed_seconds':round(time.monotonic()-t,2)},ensure_ascii=False),flush=True)
    # Emit retrieval inputs first. Metadata order and npz indices are explicit contracts.
    json_write(OUT/'data/inventory.json',records)
    np.savez_compressed(OUT/'data/gray128x72.npz',gray=gray_stack,indices=np.arange(len(rows),dtype=np.int32))
    print('FEATURES_READY',flush=True)

    physical_images=sorted(str(p) for p in (DATA/'images').rglob('*') if p.is_file() or p.is_symlink())
    physical_labels=sorted(str(p) for p in (DATA/'labels').rglob('*') if p.is_file() or p.is_symlink())
    orphan_images=sorted(set(physical_images)-expected_images); orphan_labels=sorted(set(physical_labels)-expected_labels)
    missing_images=sorted(expected_images-set(physical_images)); missing_labels=sorted(expected_labels-set(physical_labels))
    for path in orphan_images+orphan_labels:
        issues.append(issue({'image_path':path if path in orphan_images else '', 'label_path':path if path in orphan_labels else ''},'orphan_physical_file','error',path,'核对metadata映射，不自动移动或删除'))
    metadata_names=Counter(r['filename'] for r in records); metadata_keys=Counter((r['split'],r['filename']) for r in records)
    hardlink_images=[v for v in image_inode.values() if len(v)>1]; hardlink_labels=[v for v in label_inode.values() if len(v)>1]
    image_dup=groups(records,'image_sha256'); pixel_dup=groups(records,'pixel_sha256')
    for kind,dups in (('duplicate_inode_image',hardlink_images),('duplicate_inode_label',hardlink_labels),('duplicate_file_sha256',image_dup),('duplicate_decoded_pixels',pixel_dup)):
        for ids in dups:
            for idx in ids: issues.append(issue(records[idx],kind,'warning',f'metadata_indices={ids}','核对样本独立性及跨split泄漏；不自动删除'))
    image_manifest=''.join(f'{r["image_path"]}\t{r["image_sha256"]}\n' for r in records)
    label_manifest=''.join(f'{r["label_path"]}\t{r["label_sha256"]}\n' for r in records)
    pixel_manifest=''.join(f'{r["image_path"]}\t{r["pixel_sha256"]}\n' for r in records)
    (OUT/'data/image-sha256.tsv').write_text(image_manifest,encoding='utf-8')
    (OUT/'data/label-sha256.tsv').write_text(label_manifest,encoding='utf-8')
    (OUT/'data/pixel-sha256.tsv').write_text(pixel_manifest,encoding='utf-8')
    # Canonical path list includes all physical files, even if metadata omitted any.
    # Present dataset has no extras; retaining a separate physical inventory makes that test explicit.
    physical_details=[]
    for typ,paths in (('image',physical_images),('label',physical_labels)):
        lookup={r[f'{typ}_path']:r.get(f'{typ}_sha256') for r in records}
        for path in paths:
            p=Path(path); st=p.lstat(); target=p.stat()
            physical_details.append({'kind':typ,'path':path,'extension':p.suffix,'symlink':p.is_symlink(),
                                     'size':target.st_size,'device':target.st_dev,'inode':target.st_ino,
                                     'mtime_ns':target.st_mtime_ns,'sha256':lookup.get(path) or file_sha(p)})
    json_write(OUT/'data/physical-inventory.json',physical_details)
    csv_write(OUT/'annotation_issues_base.csv',('image_path','label_path','split','status','issue_type','severity','evidence','recommendation','requires_review','review_result'),issues)
    excluded=[]
    for r in records:
        if r['meta']['annotation_status']!='reviewed_excluded': continue
        original=re.findall(r'原处置=([^；]+)',r['meta'].get('label_review_note',''))
        excluded.append({'image_path':r['image_path'],'label_path':r['label_path'],'split':r['split'],
                         'status':'reviewed_excluded','original_disposition':original[-1] if original else '未记录',
                         'valid_label_count':r['valid_box_count'],'parsed_box_count':r['box_count'],
                         'label_valid':str(r['label_valid']).lower(),'label_error':'; '.join(r['label_errors']),
                         'No Ball':r['meta'].get('No Ball',''),'raw_directory_scanned_by_yaml':'true',
                         'training_filter_verified':'pending_training_safety_audit',
                         'recommendation':'维持排除；不得因空label作为确认负例；若重新纳入，需球框及场景完整复审',
                         'review_result':''})
    csv_write(OUT/'excluded_samples_audit.csv',('image_path','label_path','split','status','original_disposition','valid_label_count','parsed_box_count','label_valid','label_error','No Ball','raw_directory_scanned_by_yaml','training_filter_verified','recommendation','review_result'),excluded)
    # Tidy distribution table; every row declares unit, universe, and denominator.
    dist=[]
    def add(scope,split,metric,category,count,denominator,unit='images',note=''):
        dist.append({'scope':scope,'split':split,'metric':metric,'category':category,'count':count,
                     'denominator':denominator,'fraction':count/denominator if denominator else 0,
                     'unit':unit,'threshold_source_or_note':note})
    for scope in ('all','usable','reviewed_excluded','reviewed_annotation','negative_confirmed'):
        all_scope=[r for r in records if scope=='all' or (scope=='usable' and r['usable']) or r['meta']['annotation_status']==scope]
        for sp in ('all','train','val','test'):
            sub=[r for r in all_scope if sp=='all' or r['split']==sp]; n=len(sub)
            add(scope,sp,'population','total',n,n)
            for k,c in Counter(r['meta']['annotation_status'] for r in sub).items(): add(scope,sp,'status',k,c,n)
            for flag in FLAGS:
                for v in ('0','1'): add(scope,sp,'flag',f'{flag}={v}',sum(r['meta'].get(flag)==v for r in sub),n)
            combos=Counter(''.join(r['meta'].get(k,'?') for k in FLAGS) for r in sub)
            for bits in (f'{k:04b}' for k in range(16)): add(scope,sp,'joint_flags',bits,combos[bits],n,note='bit order: Small,Occluded,Blurred,No Ball; multi-label, not mutually exclusive classes')
            boxes=[b for r in sub for b in r['boxes'] if b['valid']]; nb=len(boxes)
            length_bins=Counter(); area_bins=Counter()
            for b in boxes:
                v=b['long_side_at_672']; key='<16' if v<16 else '16-<30' if v<30 else '30-<40' if v<40 else '40-<50' if v<50 else '50-<96' if v<96 else '>=96'
                length_bins[key]+=1
                a=b['area_fraction']; key='<0.0001' if a<.0001 else '0.0001-<0.001' if a<.001 else '0.001-<0.01' if a<.01 else '0.01-<0.1' if a<.1 else '>=0.1'
                area_bins[key]+=1
            for k in ('<16','16-<30','30-<40','40-<50','50-<96','>=96'):
                add(scope,sp,'bbox_long_side_at_672_px',k,length_bins[k],nb,'valid_boxes','long side=max(w_px,h_px)*672/image_long_side; project Small boundary approximately40px; extra bins descriptive; occluded fragments are not full-ball scale')
            for k in ('<0.0001','0.0001-<0.001','0.001-<0.01','0.01-<0.1','>=0.1'):
                add(scope,sp,'bbox_area_fraction',k,area_bins[k],nb,'valid_boxes','area=w_norm*h_norm; descriptive bins, not a quality criterion')
    csv_write(OUT/'split_distribution.csv',('scope','split','metric','category','count','denominator','fraction','unit','threshold_source_or_note'),dist)
    after={p:file_sha(Path(p)) for p in originals}
    summary={
        'started_at_utc':started,'finished_at_utc':now(),'elapsed_seconds':time.monotonic()-t,
        'implementation':str(Path(__file__)),'runtime':{'python':sys.version,'numpy':np.__version__,'opencv':cv2.__version__,'pillow':PIL_VERSION,'platform':platform.platform(),'nice':os.nice(0),'cv2_threads':cv2.getNumThreads(),'OMP_NUM_THREADS':os.environ['OMP_NUM_THREADS']},
        'source_hashes_before':originals,'source_hashes_after':after,'source_hashes_unchanged':originals==after,
        'definition_usable':'image and label valid; label_review_required=scene_review_required=0; reviewed_annotation + valid nonempty class0 label + No Ball=0 OR negative_confirmed + valid empty label + No Ball=1; reviewed_excluded always excluded',
        'full_decode_method':'read bytes once, PIL.Image.open(BytesIO).load(), convert RGB; all metadata images scanned; no verify-only substitution',
        'pixel_sha256_definition':'SHA256(big endian uint32 width + uint32 height + decoded RGB row-major bytes); no EXIF orientation transposition',
        'phash_definition':'OpenCV RGB2GRAY, INTER_AREA resize32x32, float32 cv2.dct, upperleft8x8 coefficients > median of63 coefficients excludingDC; all64 bits includingDC; row-major top-left is most significant bit; 16 lowercase hex',
        'dhash_definition':'OpenCV RGB2GRAY, INTER_AREA resize9x8; compare right pixel > left pixel; row-major64 booleans, first is most significant bit;16 lowercase hex',
        'gray_npz_definition':'gray uint8[N,72,128]; indices int32 arange(N); metadata order; RGB2GRAY then INTER_AREA resize128x72, no crop or geometric alignment; aspect ratio slightly stretched for672x376; SSIM on these thumbnails is candidate evidence only and cannot prove semantic duplication',
        'thresholds':{'YOLO_boundary_tolerance':EPS,'tiny_bbox':'min native side<2px or native area<4px2','duplicate_bbox_IoU':.9,'blank':'gray std<2 OR entropy<0.5bit OR black(gray<=5)>0.99 OR white(gray>=250)>0.99','Small_risk':'only Occluded=0; Small1 and anybox_longside672>50, or Small0 and allbox_longside672<30; not error verdict','Occluded_risk':'No automatic judgment; Occluded0 with box near boundary<0.002 is visual candidate only','Blurred':'No automatic judgment from global sharpness; human interpretation of directional ball/camera motion required'},
        'policy':policy,'counts':{'metadata':len(records),'physical_images':len(physical_images),'physical_labels':len(physical_labels),'image_full_decode_success':sum(r['image_valid'] for r in records),'label_valid':sum(r['label_valid'] for r in records),'usable':sum(r['usable'] for r in records),'excluded':len(excluded),'usable_positive':sum(r['usable'] and bool(r['valid_box_count']) for r in records),'usable_negative':sum(r['usable'] and not r['valid_box_count'] for r in records),'usable_boxes':sum(r['valid_box_count'] for r in records if r['usable']),'all_parsed_boxes':sum(r['box_count'] for r in records),'all_valid_boxes':sum(r['valid_box_count'] for r in records),'issues':len(issues)},
        'physical_mapping':{'missing_images':missing_images,'missing_labels':missing_labels,'orphan_images':orphan_images,'orphan_labels':orphan_labels,'metadata_duplicate_filenames':{k:v for k,v in metadata_names.items() if v>1},'metadata_duplicate_split_filename':{str(k):v for k,v in metadata_keys.items() if v>1},'image_symlinks':[p for p in physical_images if Path(p).is_symlink()],'label_symlinks':[p for p in physical_labels if Path(p).is_symlink()],'directory_symlinks':[str(p) for d in (DATA/'images',DATA/'labels') for p in d.rglob('*') if p.is_dir() and p.is_symlink()],'image_hardlink_index_groups':hardlink_images,'label_hardlink_index_groups':hardlink_labels},
        'file_sha_duplicate_index_groups':image_dup,'pixel_sha_duplicate_index_groups':pixel_dup,
        'resolutions':dict(Counter(f'{r["width"]}x{r["height"]}' for r in records)),'formats':dict(Counter(r.get('format','INVALID') for r in records)),
        'statuses':dict(Counter(r['meta']['annotation_status'] for r in records)),'issues_by_type':dict(Counter(i['issue_type'] for i in issues)),
        'label_error_files':[{'index':r['index'],'image_path':r['image_path'],'label_path':r['label_path'],'errors':r['label_errors']} for r in records if not r['label_valid']],
        'blank_candidate_indices':[r['index'] for r in records if r['blank_candidate']],
        'aggregate_hashes':{'image_sha_manifest':sha(image_manifest.encode()),'label_sha_manifest':sha(label_manifest.encode()),'pixel_sha_manifest':sha(pixel_manifest.encode()),'physical_inventory_sha256':file_sha(OUT/'data/physical-inventory.json')},
        'read_only_evidence':'source metadata/YAML/policy/report hashes before and after equal; all original image and label content hashes recorded; script opens canonical data only for reading; no model loaded; no training or production inference',
        'limitations':['No manual semantic judgment from image statistics','Occluded and Blurred need visual interpretation under project policy','Historical box counts can differ after human review and do not imply an annotation error','Boundary-invalid labels remain preserved and excluded; parsed box count differs from valid box count','Read-only audit checks hashes; it does not make a training loader safe by itself']}
    json_write(OUT/'data/inventory-summary.json',summary)
    print(json.dumps({'complete':True,'counts':summary['counts'],'issues_by_type':summary['issues_by_type'],'source_hashes_unchanged':summary['source_hashes_unchanged']},ensure_ascii=False),flush=True)

def enrich_excluded_context():
    """Idempotent reporting-only enrichment from the already decoded inventory."""
    records=json.loads((OUT/'data/inventory.json').read_text(encoding='utf-8'))
    summary_path=OUT/'data/inventory-summary.json'
    summary=json.loads(summary_path.read_text(encoding='utf-8'))
    issues_path=OUT/'annotation_issues_base.csv'
    with issues_path.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f); fields=reader.fieldnames; issues=list(reader)
    issues=[x for x in issues if x['issue_type']!='excluded_NoBall_label_context']
    by_path={r['image_path']:r for r in records}
    for x in issues:
        if x['issue_type']=='label_format_or_geometry':
            r=by_path[x['image_path']]
            bad=[{'line':b['line'],'xywhn':b['xywhn'],'xyxy':b['xyxy']} for b in r['boxes'] if not b['valid']]
            x['evidence']=x['evidence'].split('; parsed_invalid_boxes=')[0]+'; parsed_invalid_boxes='+json.dumps(bad,ensure_ascii=False)
    excluded_path=OUT/'excluded_samples_audit.csv'
    with excluded_path.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f); exfields=list(reader.fieldnames); excluded=list(reader)
    if 'NoBall_label_context' not in exfields: exfields.insert(exfields.index('raw_directory_scanned_by_yaml'),'NoBall_label_context')
    contexts=Counter()
    for x in excluded:
        r=by_path[x['image_path']]; nb=r['meta'].get('No Ball',''); count=r['valid_box_count']
        if not r['label_valid']: context='invalid_label_preserved_reference'
        elif nb=='0' and count==0: context='NoBall0_empty_label_uncertain_excluded'
        elif nb=='1' and count>0: context='NoBall1_nonempty_label_excluded_conflict'
        elif nb=='1' and count==0: context='NoBall1_empty_label_still_excluded'
        else: context='NoBall0_nonempty_label_still_excluded'
        x['NoBall_label_context']=context; contexts[context]+=1
        if nb not in ('0','1') or (nb=='0' and count==0) or (nb=='1' and count>0):
            issues.append(issue(r,'excluded_NoBall_label_context','info',f'No Ball={nb}; valid_boxes={count}; label_valid={r["label_valid"]}; context={context}','该图已排除；No Ball与空/非空框上下文仅单列追溯，不能直接判错或转为确认负例',False))
    csv_write(excluded_path,exfields,excluded)
    csv_write(issues_path,fields,issues)
    summary['excluded_NoBall_label_context']=dict(contexts)
    summary['counts']['issues']=len(issues)
    summary['issues_by_type']=dict(Counter(i['issue_type'] for i in issues))
    summary['physical_mapping']['metadata_duplicate_label_paths']={k:v for k,v in Counter(r['label_path'] for r in records).items() if v>1}
    summary['excluded_valid_label_statistics']={
        'valid_nonempty_files':sum(r['label_valid'] and r['valid_box_count']>0 for r in records if r['meta']['annotation_status']=='reviewed_excluded'),
        'valid_empty_files':sum(r['label_valid'] and r['valid_box_count']==0 for r in records if r['meta']['annotation_status']=='reviewed_excluded'),
        'invalid_files':sum(not r['label_valid'] for r in records if r['meta']['annotation_status']=='reviewed_excluded')}
    summary['reporting_enriched_at_utc']=now()
    summary['implementation_sha256']=file_sha(Path(__file__))
    summary['feature_artifact_sha256']={str(p.relative_to(OUT)):file_sha(p) for p in (OUT/'data/inventory.json',OUT/'data/gray128x72.npz')}
    json_write(summary_path,summary)
    print(json.dumps({'reporting_enriched':True,'excluded_NoBall_label_context':dict(contexts),'issues':len(issues)},ensure_ascii=False))

if __name__=='__main__':
    if '--enrich-excluded' not in sys.argv: main()
    enrich_excluded_context()
