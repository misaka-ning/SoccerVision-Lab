import json,os,collections,datetime
D=os.path.dirname(os.path.abspath(__file__))
a=json.load(open(D+'/inventory.json'));notes=json.load(open(D+'/notes.json'));ledger=json.load(open(D+'/opened.json'))
helper_dir=os.path.dirname(D)+'/native-group1-tail'
h=json.load(open(helper_dir+'/decisions.json'));hs=json.load(open(helper_dir+'/summary.json'))
keys=['Small','Occluded','Blurred','No Ball']
for x in h:
 n=x['n'];assert a[n]['filename']==x['filename'];assert not a[n]['boxes']
 q=notes[str(n)];q['native_evidence']=sorted(set(q.get('native_evidence',[])+x['native_evidence']))
 q['native_observer']='/root/native_group1_tail';q['native_conclusion']=x['conclusion']
 if x['conclusion']=='yes':
  q['detail']=x['reason'];q['label']='approve_negative';q['scene']='approve';q['flags']=x['flags']
 else:
  q['detail']=x['reason']+' 当前空label保留补框/可见性审核，不以空检测通过负样本。'
  q['label']='retain';q['scene']='retain';q['flags']=None
ledger['native_own']=list(ledger.get('native_own',ledger['native']))
ledger['native_helper']=hs['opened_pages']
ledger['native']=sorted(set(ledger['native']+hs['opened_pages']))
ledger['native_helper_crops']=sorted(set(p for x in h for p in x['native_evidence'] if '/empty-native/' not in p))
ledger['native_helper_observer']='/root/native_group1_tail'
assert len(a)==len(notes)==1536 and set(notes)=={str(n) for n in range(1536)}
assert ledger['full']==list(range(32)) and ledger['roi']==list(range(64))
assert len(ledger['native'])==33 and len(h)==94
out=[]
for n,r in enumerate(a):
 q=notes[str(n)];m=r['meta'];flags={k:m[k] for k in keys}; flags.update(q['flags'] or {})
 label=q['label']
 confirmed=m['label_review_required']=='0' and m['annotation_status'] in ['reviewed_annotation','provided_annotation','negative_confirmed']
 if confirmed:label='already_confirmed'
 elif label=='auto':label='retain'
 if label=='approve_positive':assert r['boxes'] and not r['parse_errors'];flags['No Ball']='0'
 if label=='approve_negative':assert not r['boxes'] and not r['label_text'].strip();flags['No Ball']='1';flags['Small']='0';flags['Occluded']='0'
 scene=q['scene']
 if m['scene_review_required']=='0' and flags=={k:m[k] for k in keys}:scene='already_confirmed'
 assert label in ['approve_positive','approve_negative','retain','already_confirmed']
 assert scene in ['approve','retain','already_confirmed']
 detail=q['detail']
 if r['boxes']:
  bs=[]
  for b in r['boxes']:
   x1,y1,x2,y2=b['xyxy'];cx=(x1+x2)/2;cy=(y1+y2)/2
   loc=('左' if cx<r['width']/3 else '右' if cx>r['width']*2/3 else '中')+('上' if cy<r['height']/3 else '下' if cy>r['height']*2/3 else '部')
   bs.append(f"框{b['box_index']+1}位于{loc}，原生{x2-x1:.1f}×{y2-y1:.1f}px，长边归一672约{max(x2-x1,y2-y1)*672/max(r['width'],r['height']):.1f}px")
  detail+=' 实际逐框ROI复核：'+'；'.join(bs)+'。'
  if label=='approve_positive':detail+=' 足球身份、完整可见外缘四边与全景球数核对一致，现框无明显漏边、内纹重复或漏球，可通过球框。'
 else:
  if label=='approve_negative':detail+=' 空标通过基于原生全景及底边/侧缘/鞋下核验，无可见足球。'
  elif label=='retain':detail+=' 当前无可靠足球框，保留待补或待确认可见性。'
 if scene=='approve':
  if flags['No Ball']=='1':
   detail+=' 四项依据：没有可见球，Small/Occluded为0；'+('整图有明确运动拖影，Blurred为1。' if flags['Blurred']=='1' else '地面和场景无明显方向性拖影，Blurred为0。')
  else:
   detail+=' 四项依据：可见足球故No Ball=0；'+('至少一个完整球为远处小球，Small=1；' if flags['Small']=='1' else '完整球尺度大于小球阈值，Small=0；')+('有明确前景覆盖球面，Occluded=1；' if flags['Occluded']=='1' else '未见前景覆盖球面，裁边不计遮挡，Occluded=0；')+('球体或全景可见拖影，Blurred=1。' if flags['Blurred']=='1' else '球体外缘与场景无明确运动拖影，轻微软化不算Blurred，Blurred=0。')
 else:detail+=' 场景四项保留当前/明确建议值；不确定字段及原因见上述实际观察，整场景不清除待审。' if scene=='retain' else ' 场景原已确认且本次无可靠改动建议，保持原确认状态。'
 if confirmed:detail+=' 已确认标注仅视觉复核，原框与原标注状态保护。'
 changes=[f'{k}:{m[k]}→{flags[k]}' for k in keys if m[k]!=flags[k]]
 if changes:detail+=' 分类建议变化：'+','.join(changes)+'；依据为上述可见球、遮挡/裁边、尺度或全景拖影观察。'
 full=D+f'/full/page-{n//48:02}.jpg';roi=D+f'/roi/page-{n//24:02}.png'
 evidence=list(q.get('native_evidence',[]))
 if r['boxes']:evidence=sorted(set(evidence+[roi]))
 if label=='approve_negative':assert any('/empty-native/' in p for p in evidence)
 out.append({'filename':r['filename'],'index':r['index'],'local_index':n,'scene_seen':True,'roi_seen':True if r['boxes'] else 'not_applicable','label_decision':label,'scene_decision':scene,'flags':flags,'reason':detail,'native_evidence':evidence,'expected_label_sha256':r['label_sha256'],'expected_image_sha256':r['image_sha256'],'confidence_level':'uncertain' if label=='retain' or scene=='retain' else 'high','label_confidence_level':'uncertain' if label=='retain' else 'high','scene_confidence_level':'uncertain' if scene=='retain' else 'high','scene_evidence':[full],'roi_evidence':[roi] if r['boxes'] else [],'review_authority':'用户授权助手逐图审核；非用户本人逐图确认','native_observer':q.get('native_observer','/root/approve_group1')})
counts=lambda key:dict(collections.Counter(x[key] for x in out))
s={'total_images':len(out),'total_current_boxes':sum(len(r['boxes']) for r in a),'scene_seen_images':len(out),'roi_seen_box_images':sum(bool(r['boxes']) for r in a),'roi_seen_boxes':sum(len(r['boxes']) for r in a),'label_decision_counts':counts('label_decision'),'scene_decision_counts':counts('scene_decision'),'confidence_counts':counts('confidence_level'),'opened':ledger,'full_page_count':32,'roi_page_count':64,'native_empty_page_count':33,'native_empty_own_page_count':17,'native_empty_helper_page_count':16,'empty_label_images':sum(not r['boxes'] for r in a),'native_empty_coverage_images':196,'zoom_page_count':len(ledger.get('zoom',[])),'helper':{'path':helper_dir,'observer':'/root/native_group1_tail','total_images':len(h),'conclusion_counts':hs['conclusion_counts']},'threshold':'原生单目长边归一672；完整球最长边≤约40px为Small，临界尺寸或模糊边界保留scene待审。裁边不等于遮挡；仅低分辨率/轻微软化不算运动Blurred。','review_authority':'用户明确委托助手对高置信度结果直接通过，本次为授权助手审核，不表示用户本人逐图确认。','protected_confirmed_labels':sum(r['meta']['label_review_required']=='0' for r in a),'official_dataset_modified':False,'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'complete_stable','unresolved_examples_local_n':[0,1,595,701,824,960,1016,1032,1159,1226,1249,1288,1332,1410,1418,1515,1520,1529]}
for fn,obj in [('notes.json',notes),('opened.json',ledger),('decisions.json',out),('summary.json',s)]:
 temp=D+'/'+fn+'.tmp';json.dump(obj,open(temp,'w'),ensure_ascii=False,indent=2);os.replace(temp,D+'/'+fn)
print(json.dumps({k:v for k,v in s.items() if k in ['total_images','total_current_boxes','label_decision_counts','scene_decision_counts','confidence_counts','native_empty_page_count','protected_confirmed_labels']},ensure_ascii=False,indent=2))
