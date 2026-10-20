import csv,json,hashlib,sys,tempfile,subprocess,time
from pathlib import Path
from PIL import Image
W=Path(__file__).parent;sys.path.insert(0,str(W));import apply_confidence_review as module
root=Path(tempfile.mkdtemp(prefix='football-approval-fixture-'));(root/'images/train').mkdir(parents=True);(root/'labels/train').mkdir(parents=True)
headers=['图片','Small','Occluded','Blurred','No Ball','split','annotation_status','scene_review_required','label_review_required','auto_box_count','preserved_box_count','label_review_note','source_video','source_frame_idx','eye','用户额外字段'];rows=[];base=[];dec=[]
for n,negative in [('positive.png',False),('negative.png',True),('uncertain.png',False)]:
 ip=root/'images/train'/n;lp=root/'labels/train'/(Path(n).stem+'.txt');Image.new('RGB',(100,60),'white').save(ip);lp.write_text('' if negative else '0 0.5 0.5 0.2 0.3333333333\n');m=dict(zip(headers,[n,'0','0','0','0','train','auto_label_needs_review','1','1','0' if negative else '1','0','原备注，含逗号\n第二行','','','','保持✓']));rows.append(m)
 b={'filename':n,'split':'train','width':100,'height':60,'image_path':str(ip),'label_path':str(lp),'image_sha256':module.io.digest(ip.read_bytes()),'label_sha256':module.io.digest(lp.read_bytes()),'meta':m,'boxes':[] if negative else [{'xyxy':[40,20,60,40]}]};base.append(b)
 d={'filename':n,'scene_seen':True,'roi_seen':True if not negative else 'not_applicable','expected_label_sha256':b['label_sha256'],'expected_image_sha256':b['image_sha256'],'flags':{k:m[k] for k in module.FLAGS},'label_decision':'approve_negative' if negative else 'approve_positive','scene_decision':'approve','reason':'测试：已实际确认类型及边界，未知列与原备注需保留。','native_evidence':[str(ip)],'confidence_level':'high'}
 if negative:d['flags']['No Ball']='1'
 if n=='uncertain.png':d.update(label_decision='retain',scene_decision='retain',confidence_level='uncertain',reason='边界不清保留待审')
 dec.append(d)
def save_csv(values):
 with (root/'metadata.csv').open('w',encoding='utf-8-sig',newline='') as f:
  wr=csv.DictWriter(f,fieldnames=headers,lineterminator='\r\n');wr.writeheader();wr.writerows(values)
save_csv(rows);bb=root/'baseline.json';dd=root/'decisions.json';bb.write_text(json.dumps(base,ensure_ascii=False));dd.write_text(json.dumps(dec,ensure_ascii=False));bi=module.io.indexed(base);di=module.io.indexed(dec);raw=(root/'metadata.csv').read_bytes();accepted=module.plan(root,bi,di)[3];assert len(accepted)==3;assert (root/'metadata.csv').read_bytes()==raw
# Negative type and independent uncertainty semantics.
assert accepted[1]['after_meta']['annotation_status']=='negative_confirmed';assert accepted[1]['after_meta']['No Ball']=='1';assert accepted[2]['after_meta']['label_review_required']=='1';assert accepted[2]['after_meta']['scene_review_required']=='1';assert all(x['after_meta']['用户额外字段']=='保持✓' for x in accepted)
# Definitive presence/absence can pass independently of an ambiguous scene tag.
partial_base=json.loads(json.dumps(base));partial_dec=json.loads(json.dumps(dec))
partial_base[0]['meta']['No Ball']='1';partial_dec[0]['scene_decision']='retain'
partial_base[1]['meta'].update({'Small':'1','Occluded':'1','Blurred':'1'});partial_dec[1]['scene_decision']='retain'
save_csv([b['meta'] for b in partial_base]);partial=module.plan(root,module.io.indexed(partial_base),module.io.indexed(partial_dec));assert len(partial[3])==3 and not partial[4]
positive_partial=partial[3][0]['after_meta'];negative_partial=partial[3][1]['after_meta']
assert positive_partial['No Ball']=='0' and positive_partial['label_review_required']=='0' and positive_partial['scene_review_required']=='1'
assert negative_partial['No Ball']=='1' and negative_partial['Small']=='0' and negative_partial['Occluded']=='0'
assert negative_partial['Blurred']=='1' and negative_partial['label_review_required']=='0' and negative_partial['scene_review_required']=='1'
save_csv(rows)
# Six-decimal GT rounding is accepted, while an actual overshoot is rejected.
module.io.label_boxes(b'0 0.545312 0.779167 0.375000 0.441667\n',boundary_tolerance=1e-6)
try:
 module.io.label_boxes(b'0 0.5 0.8 0.2 0.42\n',boundary_tolerance=1e-6)
except ValueError:pass
else:raise AssertionError('real boundary crossing accepted')
# A fresh human classification causes a skip, including scene-only changes.
changed=[dict(x) for x in rows];changed[0]['Small']='1';save_csv(changed);p=module.plan(root,bi,di);assert len(p[3])==2 and len(p[4])==1;save_csv(rows)
# Any new label bytes cause a skip.
lp=root/'labels/train/positive.txt';old=lp.read_bytes();lp.write_bytes(b'0 0.5 0.5 0.3 0.3\n');p=module.plan(root,bi,di);assert len(p[3])==2 and len(p[4])==1;lp.write_bytes(old)
# A true native Qt lock conflict aborts before any metadata mutation.
locklist=root/'held-locks.json';locklist.write_text(json.dumps([str(root/'metadata.csv')+'.review.lock']));holder=subprocess.Popen([str(W/'qt_review_lock_runner'),'--lock-list',str(locklist),'--',sys.executable,'-c','import time; time.sleep(15)'])
try:
 for _ in range(60):
  if Path(str(root/'metadata.csv')+'.review.lock').exists():break
  time.sleep(.05)
 blocked=subprocess.run([sys.executable,str(W/'apply_confidence_review.py'),'--dataset',str(root),'--baseline',str(bb),'--decisions',str(dd),'--audit-root',str(root/'audit'),'--apply'],capture_output=True,text=True);assert blocked.returncode==73;assert (root/'metadata.csv').read_bytes()==raw
finally:
 holder.terminate();holder.wait();Path(str(root/'metadata.csv')+'.review.lock').unlink(missing_ok=True)
# Save under real QLockFile; labels and images remain identical.
label_bytes={p:p.read_bytes() for p in (root/'labels').rglob('*.txt')};image_bytes={p:p.read_bytes() for p in (root/'images').rglob('*.png')};result=subprocess.run([sys.executable,str(W/'apply_confidence_review.py'),'--dataset',str(root),'--baseline',str(bb),'--decisions',str(dd),'--audit-root',str(root/'audit'),'--apply'],capture_output=True,text=True);assert result.returncode==0,result.stderr
saved=list(csv.DictReader((root/'metadata.csv').open(encoding='utf-8-sig',newline='')));assert saved[0]['label_review_required']=='0' and saved[1]['label_review_required']=='0';assert saved[2]['label_review_required']=='1';assert (root/'metadata.csv').read_bytes().startswith(b'\xef\xbb\xbf');assert b'\r\n' in (root/'metadata.csv').read_bytes();assert all(p.read_bytes()==x for p,x in label_bytes.items());assert all(p.read_bytes()==x for p,x in image_bytes.items());assert all(x['用户额外字段']=='保持✓' and x['label_review_note'].startswith('原备注，含逗号\n第二行') for x in saved)
checks={'dry_run_zero_writes':True,'positive_negative_semantics':True,'uncertainty_remains_pending':True,'partial_label_approval_resolves_presence_but_retains_unknown_scene':True,'decimal_rounding_allowed_real_boundary_crossing_rejected':True,'fresh_human_scene_change_skipped':True,'fresh_label_change_skipped':True,'qt_lock_conflict_zero_writes':True,'metadata_only_atomic_apply_preserves_bom_newlines_unknown_columns_notes_images_labels':True};(W/'safety-fixture-result.json').write_text(json.dumps({'checks':checks,'fixture':str(root)},ensure_ascii=False,indent=2));print(json.dumps(checks,ensure_ascii=False))
