#!/usr/bin/env python3
"""Persist user-authorized assistant visual review. Default: read-only plan.

Only metadata is changed; labels, images and YAML stay byte-identical. Exact label
and image SHA and current field values must match the visual baseline. The native
Qt QLockFile runner interoperates with the existing live reviewer.
"""
import argparse,json,sys,subprocess,math,os
from pathlib import Path
from datetime import datetime,timezone
from uuid import uuid4
import audit_io as io
HERE=Path(__file__).parent
FLAGS=('Small','Occluded','Blurred','No Ball')
PENDING=('auto_label_needs_review','needs_visibility_review','needs_manual_bbox_annotation')
LABEL_CHOICES={'approve_positive','approve_negative','retain','already_confirmed'}
SCENE_CHOICES={'approve','retain','already_confirmed'}

def plan(root,baseline,decisions):
 root=root.absolute();meta=io.regular_under(root/'metadata.csv',root);raw=meta.read_bytes();parsed=io.csv_parts(raw);latest={r['图片']:r for r in parsed['rows']};accepted=[];skipped=[]
 for name,d in decisions.items():
  try:
   b=baseline[name];old=b['meta'];current=latest[name]
   # Protect every existing baseline field, including fresh human scene decisions.
   if any(current.get(k)!=v for k,v in old.items()):raise ValueError('Baseline后metadata字段变化，保留新人工修改')
   if d.get('expected_label_sha256')!=b['label_sha256'] or d.get('expected_image_sha256')!=b['image_sha256']:raise ValueError('Decision SHA 与视觉基线不一致')
   if not d.get('scene_seen') or (b['boxes'] and d.get('roi_seen') not in (True,'true')):raise ValueError('缺少逐图/逐框实际视觉覆盖')
   reason=d.get('reason','').strip()
   if not reason:raise ValueError('缺少具体审核依据')
   ld=d.get('label_decision');sd=d.get('scene_decision')
   if ld not in LABEL_CHOICES or sd not in SCENE_CHOICES:raise ValueError('未知审核决定')
   label=io.regular_under(Path(b['label_path']),root);img=io.regular_under(Path(b['image_path']),root)
   if io.digest(label.read_bytes())!=b['label_sha256']:raise ValueError('视觉审核后label已变化，保留新修改')
   if io.digest(img.read_bytes())!=b['image_sha256']:raise ValueError('视觉审核后图片已变化')
   # Match the canonical validator's tolerance for six-decimal YOLO rounding.
   # At 1280px this is at most 0.00128px; source labels are never rewritten.
   boxes=io.label_boxes(label.read_bytes(),boundary_tolerance=1e-6);new=dict(current);fields=[]
   flag_updates=d.get('flags',{k:current[k] for k in FLAGS})
   if set(flag_updates)!=set(FLAGS) or any(v not in ('0','1') for v in flag_updates.values()):raise ValueError('四场景flags不合法')
   if sd=='approve':
    for k in FLAGS:
     if new[k]!=flag_updates[k]:fields.append(k)
     new[k]=flag_updates[k]
    if new['scene_review_required']!='0':fields.append('scene_review_required')
    new['scene_review_required']='0'
   elif sd=='already_confirmed' and old['scene_review_required']=='1':raise ValueError('待审场景不能标为already_confirmed')
   label_pending=old['label_review_required']=='1' or old['annotation_status'] in PENDING
   if ld=='already_confirmed' and label_pending:raise ValueError('待审label不能标为already_confirmed')
   # Label certainty establishes presence/absence even if a different scene
   # attribute (e.g. Small at 40px or mild blur) still needs review.
   if sd=='retain' and old['scene_review_required']=='1':
    certain_presence={}
    if ld=='approve_positive' and boxes and flag_updates['No Ball']=='0':
     certain_presence={'No Ball':'0'}
    elif ld=='approve_negative' and not boxes and label.stat().st_size==0 and d.get('native_evidence'):
     if any(flag_updates[k]!='0' for k in ('Small','Occluded')) or flag_updates['No Ball']!='1':raise ValueError('明确无球的部分通过flags矛盾')
     certain_presence={'No Ball':'1','Small':'0','Occluded':'0'}
    for k,v in certain_presence.items():
     if new[k]!=v:fields.append(k)
     new[k]=v
   if ld in ('approve_positive','approve_negative'):
    if ld=='approve_positive' and (not boxes or new['No Ball']!='0'):raise ValueError('正样本通过需合法非空球框且No Ball=0')
    if ld=='approve_negative':
     if boxes or label.stat().st_size!=0 or new['No Ball']!='1':raise ValueError('负样本通过需零字节label且No Ball=1')
     if not d.get('native_evidence'):raise ValueError('负样本通过缺少原生边缘复核证据')
    new['annotation_status']='reviewed_annotation' if boxes else 'negative_confirmed';new['label_review_required']='0';fields+=['annotation_status','label_review_required']
   # A confirmed negative cannot carry a ball-specific scene attribute.
   if new['No Ball']=='1' and any(new[k]=='1' for k in ('Small','Occluded')):
    if new['label_review_required']=='0' and new['scene_review_required']=='0':raise ValueError('无球与Small/Occluded冲突，不能完全通过')
   if new['label_review_required']=='0':
    if boxes and new['No Ball']=='1':raise ValueError('已通过球框与No Ball冲突')
    if not boxes and new['No Ball']!='1':raise ValueError('已通过空label不能No Ball=0')
   marker='2026-10-14 用户授权助手视觉复核：'
   outcome=('球框通过；' if ld in ('approve_positive','approve_negative') else '')+('场景通过；' if sd=='approve' else '')
   if ld=='retain' or sd=='retain':outcome+='不确定项继续待审；'
   suffix=marker+outcome+reason+'；审核labelSHA256='+b['label_sha256']+'；审计来源=confidence-review-20261014。'
   if suffix not in new['label_review_note']:new['label_review_note']=(new['label_review_note']+' '+suffix).strip();fields.append('label_review_note')
   if new==current:skipped.append({'filename':name,'reason':'状态及记录无变化'});continue
   accepted.append({'filename':name,'split':current['split'],'before_meta':dict(current),'after_meta':new,'fields_changed':sorted(set(fields)),'label_sha256':b['label_sha256'],'image_sha256':b['image_sha256'],'label_path':str(label),'image_path':str(img),'label_decision':ld,'scene_decision':sd,'confidence_level':d.get('confidence_level'),'reason':reason,'native_evidence':d.get('native_evidence',[])})
  except (KeyError,ValueError,OSError,UnicodeError) as e:skipped.append({'filename':name,'reason':str(e)})
 return meta,raw,parsed,accepted,skipped

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--decisions',type=Path,required=True);p.add_argument('--audit-root',type=Path,default=HERE/'apply-audits');p.add_argument('--apply',action='store_true');p.add_argument('--locked',action='store_true');p.add_argument('--baseline-sha');p.add_argument('--decisions-sha');a=p.parse_args();bb=a.baseline.read_bytes();db=a.decisions.read_bytes()
 if (a.baseline_sha and io.digest(bb)!=a.baseline_sha) or (a.decisions_sha and io.digest(db)!=a.decisions_sha):raise SystemExit('基线/决策在获取锁时变化')
 baseline=io.indexed(json.loads(bb));decisions=io.indexed(json.loads(db));metadata,raw,parsed,accepted,skipped=plan(a.dataset,baseline,decisions)
 if not a.apply and not a.locked:
  print(json.dumps({'mode':'dry_run','accepted':len(accepted),'skipped':skipped,'label_approvals':sum(r['label_decision'].startswith('approve') for r in accepted),'scene_approvals':sum(r['scene_decision']=='approve' for r in accepted),'fully_cleared':sum(r['after_meta']['label_review_required']=='0' and r['after_meta']['scene_review_required']=='0' for r in accepted)},ensure_ascii=False,indent=2));return
 a.audit_root.mkdir(parents=True,exist_ok=True)
 if not a.locked:
  paths=sorted({str(a.dataset/'labels'/baseline[n]['split']/(Path(n).stem+'.txt'))+'.review.lock' for n in decisions if n in baseline});paths.append(str(a.dataset/'metadata.csv')+'.review.lock');lp=a.audit_root/('locks-'+uuid4().hex+'.json');io.save_exclusive(lp,json.dumps(paths).encode())
  cmd=[str(HERE/'qt_review_lock_runner'),'--lock-list',str(lp),'--',sys.executable,str(Path(__file__).resolve()),'--dataset',str(a.dataset),'--baseline',str(a.baseline),'--decisions',str(a.decisions),'--audit-root',str(a.audit_root),'--baseline-sha',io.digest(bb),'--decisions-sha',io.digest(db),'--locked']
  try:raise SystemExit(subprocess.run(cmd).returncode)
  finally:lp.unlink(missing_ok=True)
 run=a.audit_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]);run.mkdir();io.save_exclusive(run/'before/metadata.csv',raw);io.save_exclusive(run/'decisions.json',db);io.save_exclusive(run/'plan.json',json.dumps({'accepted':accepted,'skipped':skipped},ensure_ascii=False,indent=2).encode())
 # Locked metadata read is latest; recheck every label before the single CSV save.
 ready=[]
 for r in accepted:
  if io.digest(Path(r['label_path']).read_bytes())!=r['label_sha256'] or io.digest(Path(r['image_path']).read_bytes())!=r['image_sha256']:skipped.append({'filename':r['filename'],'reason':'保存前图或label再次变化'})
  else:ready.append(r)
 replacement=io.csv_update(parsed,{r['filename']:r['after_meta'] for r in ready});io.atomic_replace(metadata,replacement,raw)
 result={'applied':ready,'skipped':skipped,'metadata_before_sha256':io.digest(raw),'metadata_after_sha256':io.digest(replacement),'labels_written':0,'images_written':0};io.save_exclusive(run/'result.json',json.dumps(result,ensure_ascii=False,indent=2).encode());print(json.dumps({'audit':str(run),'applied':len(ready),'skipped':len(skipped),'labels_written':0,'images_written':0},ensure_ascii=False))
if __name__=='__main__':main()
