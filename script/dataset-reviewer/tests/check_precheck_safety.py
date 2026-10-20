#!/usr/bin/env python3
"""Fixture checks for manual-work protection and pending-only writes."""
import tempfile,json,io,csv,copy,contextlib,sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'maintenance'))
import apply_precheck as a
from functools import partial
a.plan=partial(a.plan,batch=2,review_date="2026-10-16")
a.apply=partial(a.apply,batch=2,review_date="2026-10-16")
h=a.h
with tempfile.TemporaryDirectory(prefix='football-precheck-') as temp:
 root=Path(temp);rows=[];base=[];qs=[]
 for i in range(3):
  name=f'frame_{i}.png';ip=root/'images/train'/name;lp=root/'labels/train'/f'frame_{i}.txt';ip.parent.mkdir(parents=True,exist_ok=True);lp.parent.mkdir(parents=True,exist_ok=True);ip.write_bytes(f'image{i}'.encode());lb=b'0 0.5 0.5 0.2 0.2\n' if i!=1 else b'';lp.write_bytes(lb)
  row={'图片':name,'Small':'0','Occluded':'0','Blurred':'0','No Ball':str(i==1).replace('True','1').replace('False','0'),'split':'train','annotation_status':'auto_label_needs_review','scene_review_required':'1','label_review_required':'1','auto_box_count':'1','preserved_box_count':'0','label_review_note':'保留已有备注','source_video':'test.avi','source_frame_idx':str(i),'eye':'left','extra_column':'保留额外列'}
  if i==2:row.update(annotation_status='reviewed_excluded',scene_review_required='0',label_review_required='0')
  rows.append(row)
  if i<2:
   b={'filename':name,'split':'train','meta':row.copy(),'width':672,'height':376,'label_sha256':h.digest(lb),'image_sha256':h.digest(ip.read_bytes()),'boxes':[{'box_index':0}] if lb else []};base.append(b);q={'filename':name,'scene_seen':True,'roi_boxes_seen':[0] if lb else [],'flags':{k:row[k] for k in a.COLS},'action':'replace' if i==0 else 'keep','boxes_xyxy':[[260,120,390,240]],'reason':'明确可见球边缘候选','evidence':[str(ip)],'expected_label_sha256':b['label_sha256'],'expected_image_sha256':b['image_sha256']};qs.append(q)
 def raw_csv(rs):
  s=io.StringIO(newline='');w=csv.DictWriter(s,fieldnames=rs[0].keys(),lineterminator='\r\n');w.writeheader();w.writerows(rs);return b'\xef\xbb\xbf'+s.getvalue().encode()
 mp=root/'metadata.csv';original=raw_csv(rows);mp.write_bytes(original)
 assert len(a.plan(root,base,qs)[3])==2
 # Every baseline metadata field, including provenance, counts and unknown fields.
 for key in rows[0]:
  r=copy.deepcopy(rows);r[0][key]=('val' if key=='split' else r[0][key]+'-new');mp.write_bytes(raw_csv(r));plan=a.plan(root,base,qs);assert any(x['filename']=='frame_0.png' for x in plan[4]),key
 mp.write_bytes(original);lp=root/'labels/train/frame_0.txt';saved=lp.read_bytes();lp.write_bytes(b'0 0.4 0.4 0.1 0.1\n');assert len(a.plan(root,base,qs)[4])==1;lp.write_bytes(saved)
 ip=root/'images/train/frame_0.png';ip.write_bytes(b'edited');assert len(a.plan(root,base,qs)[4])==1;ip.write_bytes(b'image0')
 with contextlib.redirect_stdout(io.StringIO()):result=a.apply(root,base,qs,root/'audit')
 after=h.csv_parts(mp.read_bytes());assert all(r['label_review_required']==r['scene_review_required']=='1' for r in after['rows'][:2]);assert after['rows'][1]['annotation_status']=='needs_visibility_review';assert after['rows'][2]==rows[2];assert after['records'][3]==h.csv_parts(original)['records'][3];assert (Path(result['audit'])/'before/labels/train/frame_0.txt').read_bytes()==saved;assert all(after['rows'][i]['extra_column']=='保留额外列' for i in range(3));assert result['user_approved']==0
 assert len(a.plan(root,base,qs)[4])==2 # Reapplying refuses changed metadata.

 for invalid in [float('nan'),float('inf'),float('-inf')]:
  try:a.encode({'boxes_xyxy':[[invalid,0,10,10]]},base[0])
  except ValueError:pass
  else:raise AssertionError('Non-finite box accepted')
 print(json.dumps({'metadata_fields_protected':len(rows[0]),'label_image_edit_protection':True,'outside_batch_raw_csv_preserved':True,'negative_stays_pending':True,'all_flags_stay_pending':True,'backup_exact':True,'second_apply_skips':True},ensure_ascii=False))
