#!/usr/bin/env python3
"""Persist visual prechecks as pending, protecting any work since the snapshot.

Dry-run is the default. --apply acquires the same QLockFile paths as the Qt GUI.
Every existing metadata field and image/label SHA is checked again under locks.
No image, YAML, split, provenance or prior note is replaced.
"""
import argparse,json,sys,subprocess,math,stat
from pathlib import Path
from datetime import datetime,timezone
from uuid import uuid4
W=Path(__file__).resolve().parent
SOURCE=W.parent/'review-reset-20261015'
SHARED=W.parent/'confidence-review-20261014'
sys.path.insert(0,str(SHARED));import audit_io as h
COLS=['Small','Occluded','Blurred','No Ball']
def save(path,obj):h.save_exclusive(path,(json.dumps(obj,ensure_ascii=False,indent=2)+'\n').encode())
def encode(q,b):
 lines=[]
 for box in q['boxes_xyxy']:
  if len(box)!=4:raise ValueError('Invalid box field count')
  x1,y1,x2,y2=map(float,box);w=b['width'];hh=b['height']
  if not all(math.isfinite(v) for v in [x1,y1,x2,y2]):raise ValueError('Non-finite box geometry')
  # Floating point rounding in the unchanged source boxes may exceed by < 1e-6px.
  if min(x1,y1)<-1e-5 or x2>w+1e-5 or y2>hh+1e-5:raise ValueError('Out-of-image proposal')
  x1=max(0,x1);y1=max(0,y1);x2=min(w,x2);y2=min(hh,y2)
  if not all(math.isfinite(v) for v in [x1,y1,x2,y2]) or x1>=x2 or y1>=y2:raise ValueError('Invalid box geometry')
  lines.append(f'0 {(x1+x2)/(2*w):.10f} {(y1+y2)/(2*hh):.10f} {(x2-x1)/w:.10f} {(y2-y1)/hh:.10f}')
 data=('\n'.join(lines)+('\n' if lines else '')).encode();h.label_boxes(data,boundary_tolerance=1e-6);return data

def plan(root,baseline,proposals,*,batch,review_date):
 mp=h.regular_under(root/'metadata.csv',root);raw=mp.read_bytes();parsed=h.csv_parts(raw);rows={r['图片']:r for r in parsed['rows']};bases=h.indexed(baseline);qs=h.indexed(proposals)
 if set(bases)!=set(qs):raise ValueError('Proposal coverage must exactly match batch baseline')
 accepted=[];skipped=[]
 for name,q in qs.items():
  b=bases[name];row=rows.get(name)
  if row!=b['meta']:
   skipped.append(dict(filename=name,reason='metadata differs from snapshot; preserve subsequent user edits'));continue
  if not q.get('scene_seen') or q.get('roi_boxes_seen')!=[x['box_index'] for x in b['boxes']]:raise ValueError(f'Missing visual coverage: {name}')
  if q.get('expected_label_sha256')!=b['label_sha256'] or q.get('expected_image_sha256')!=b['image_sha256']:raise ValueError(f'Proposal baseline mismatch: {name}')
  if set(q['flags'])!=set(COLS) or any(v not in ['0','1'] for v in q['flags'].values()):raise ValueError(f'Invalid flags: {name}')
  if q['action'] not in ['keep','replace','needs_manual_bbox_annotation','needs_visibility_review']:raise ValueError('Invalid action')
  if not q.get('reason') or not q.get('evidence') or any(not Path(e).is_file() for e in q['evidence']):raise ValueError(f'Missing visual evidence: {name}')
  split=row['split'];lp=h.regular_under(root/'labels'/split/(Path(name).stem+'.txt'),root);ip=h.regular_under(root/'images'/split/name,root);old=lp.read_bytes()
  if h.digest(old)!=b['label_sha256'] or h.digest(ip.read_bytes())!=b['image_sha256']:
   skipped.append(dict(filename=name,reason='image/label differs from snapshot; preserve subsequent edits'));continue
  new=encode(q,b) if q['action']=='replace' else old
  boxes=h.label_boxes(new,boundary_tolerance=1e-6)
  if q['flags']['No Ball']=='1' and boxes:raise ValueError(f'No Ball conflicts with retained boxes: {name}')
  pending=dict(row);pending.update(q['flags']);pending.update(label_review_required='1',scene_review_required='1')
  pending['annotation_status']=q['action'] if q['action'] in ['needs_manual_bbox_annotation','needs_visibility_review'] else ('auto_label_needs_review' if boxes else 'needs_visibility_review')
  note=f'{review_date} 第{batch}批助手预审（非最终通过）：'+q['reason']
  if not boxes and q['flags']['No Ball']=='1':note+=' 候选无球，仍需用户确认。'
  pending['label_review_note']=(row['label_review_note']+' '+note+' 球框和四类分类均保留待用户复查。').strip()
  accepted.append(dict(filename=name,split=split,path=lp,image=ip,original=old,replacement=new,pending_meta=pending,proposal=q))
 return mp,raw,parsed,accepted,skipped

def summary(accepted,skipped):
 return dict(prechecked=len(accepted),labels_changed=sum(x['original']!=x['replacement'] for x in accepted),boxes_before=sum(len(h.label_boxes(x['original'],boundary_tolerance=1e-6)) for x in accepted),boxes_after=sum(len(h.label_boxes(x['replacement'],boundary_tolerance=1e-6)) for x in accepted),skipped=skipped,user_approved=0)

def apply(root,baseline,proposals,out,*,batch,review_date):
 mp,raw,parsed,accepted,skipped=plan(root,baseline,proposals,batch=batch,review_date=review_date)
 run=out/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]);run.mkdir(parents=True,exist_ok=False)
 save(run/'proposals.json',proposals);save(run/'baseline.json',baseline)
 h.save_exclusive(run/'before/metadata.csv',raw,stat.S_IMODE(mp.stat().st_mode))
 for x in accepted:
  h.save_exclusive(run/'before/labels'/x['split']/x['path'].name,x['original'],stat.S_IMODE(x['path'].stat().st_mode))
  if x['replacement']!=x['original']:h.save_exclusive(run/'proposed/labels'/x['split']/x['path'].name,x['replacement'])
 # Recheck protected images and labels after backups, before any mutation.
 bases=h.indexed(baseline);ready=[]
 for x in accepted:
  if x['path'].read_bytes()!=x['original'] or h.digest(x['image'].read_bytes())!=bases[x['filename']]['image_sha256']:skipped.append(dict(filename=x['filename'],reason='Changed during backup; preserved'))
  else:ready.append(x)
 replacement=h.csv_update(parsed,{x['filename']:x['pending_meta'] for x in ready})
 if ready:h.atomic_replace(mp,replacement,raw)
 changed=[];failed=[]
 for x in ready:
  if x['replacement']==x['original']:continue
  try:h.atomic_replace(x['path'],x['replacement'],x['original']);changed.append(x['filename'])
  except Exception as exc:failed.append(dict(filename=x['filename'],reason=str(exc)))
 result=summary(ready,skipped);result['scene_rows_changed']=sum(any(x['pending_meta'][k]!=bases[x['filename']]['meta'][k] for k in COLS) for x in ready);result.update(audit=str(run),labels_changed=len(changed),changed_labels=changed,failed_labels=failed,metadata_after_sha256=h.digest(replacement),created_at_utc=datetime.now(timezone.utc).isoformat())
 save(run/'result.json',result);print(json.dumps(result,ensure_ascii=False))
 if failed:raise SystemExit(1)
 return result

def main():
 a=argparse.ArgumentParser();a.add_argument('--batch',type=int,required=True,choices=range(1,10));a.add_argument('--review-date',required=True);a.add_argument('--dataset',type=Path,default=Path('/home/misaka/workspace/datasets'));a.add_argument('--baseline',type=Path);a.add_argument('--proposals',type=Path);a.add_argument('--output',type=Path,default=W/'applied');a.add_argument('--apply',action='store_true');a.add_argument('--locked',action='store_true');args=a.parse_args()
 datetime.strptime(args.review_date,'%Y-%m-%d')
 args.baseline=args.baseline or SOURCE/f'batch-{args.batch:03d}'/'inventory.json'
 args.proposals=args.proposals or SOURCE/f'batch-{args.batch:03d}'/'proposals.json'
 root=args.dataset.resolve();baseline=h.read_json(args.baseline);proposals=h.read_json(args.proposals)
 expected=(SOURCE/'batches'/f'batch-{args.batch:03d}.txt').read_text().splitlines()
 if set(expected)!=set(h.indexed(baseline)) or len(expected)!=len(baseline):raise ValueError('Baseline does not match immutable batch list')
 if args.apply and not args.locked:
  locks=sorted([str(root/'labels'/b['split']/(Path(b['filename']).stem+'.txt'))+'.review.lock' for b in baseline]+[str(root/'metadata.csv')+'.review.lock']);locklist=W/('apply-locks-'+uuid4().hex[:8]+'.json');save(locklist,locks)
  cmd=[str(SHARED/'qt_review_lock_runner'),'--lock-list',str(locklist),'--',sys.executable,str(Path(__file__).resolve()),'--dataset',str(root),'--baseline',str(args.baseline.resolve()),'--proposals',str(args.proposals.resolve()),'--output',str(args.output.resolve()),'--batch',str(args.batch),'--review-date',args.review_date,'--apply','--locked'];raise SystemExit(subprocess.run(cmd).returncode)
 if args.apply:apply(root,baseline,proposals,args.output,batch=args.batch,review_date=args.review_date)
 else:
  _,_,_,accepted,skipped=plan(root,baseline,proposals,batch=args.batch,review_date=args.review_date);result=summary(accepted,skipped);result['scene_rows_changed']=sum(any(x['pending_meta'][k]!=h.indexed(baseline)[x['filename']]['meta'][k] for k in COLS) for x in accepted);print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
