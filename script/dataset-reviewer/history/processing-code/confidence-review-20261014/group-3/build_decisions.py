import json,os,hashlib,collections
D=os.path.dirname(__file__);rows=json.load(open(D+'/inventory.json'));d=json.load(open(D+'/visual-notes.json'));nm=json.load(open(D+'/native-map.json'));tags=['Small','Occluded','Blurred','No Ball']
positive={i for a,b in d['positive_ranges'] for i in range(a,b+1)};negative=set(d['negative']);sretain=set(d['scene_retain']);sapprove=set(d['scene_only_approve']);d['retain']['1467']='足球强纵向拖影且被下图边裁切，原生ROI确认现裁切框四边仍不够清楚；原人工框已被候选修正，当前label仍pending，保留复核'
negative_reasons={}
for ns,reason in [([8,9],'原生全图显示黄裤人脚、灰地面与机器人；脚后和四边均没有可见足球'),([104],'原生全图显示灯架、黄裤人、机器人和空地面；右边界及最下沿没有足球'),([171,172],'原生全图仅有人鞋、玻璃门与地面，最下沿没有足球，整图明显运动拖影'),([183,184],'原生全图只见灰鞋和黑裤及地面，前后脚下和底边均无可见足球，整图有运动拖影'),([213,214],'原生全图和底边看到机器人的金属足板、黑鞋及器材箱，没有球形足球'),([216,218,219,220,221],'原生全图及底边2倍确认白色窄条是黑色器材的把手或反光；器材旁及四边无可见足球'),([237,238,255,256,263,264],'原生全图仅机器人、器材和黑裤鞋；最下沿与器材脚下无可见足球，整图有运动拖影'),([521,522],'原生全图仅地面、灰鞋、椅脚和底部黑色器材；器材白色部分为方形把手，四边无可见足球'),([523,524],'原生全图只有地面、灰鞋和器材，没有可见足球，整体画面有拖影'),([561,562],'原生全图及底边2倍确认底部白物是平面的方形地面标记；没有圆球或足球面板，整图明显拖影'),([751,752],'原生全图及机器人脚下4倍查看，只见机器人金属脚与人鞋，足球没有可见球体；整体画面有拖影'),([1129,1130],'原生全图及底边2倍确认白色物是平面地面标记，球体未出现在鞋下或四边；整图明显拖影'),([1394,1395],'原生全图显示人裤腿、玩偶、展示底座，地面及画面四边均无可见足球'),([1410,1411],'原生全图仅人鞋、器材与玻璃门，鞋下和最下沿没有足球；整图明显运动模糊'),([1418,1419],'原生全图为室内仓库空地面及远处人、器材，四边和地面没有可见足球；灯光和整图有明显弧形运动拖影')]:
 for n in ns:negative_reasons[n]=reason
extra_evidence={138:['detail-138.png'],301:['detail-301.png'],418:['detail-418.png'],106:['detail-106.png'],1390:['extra-1390.png'],1391:['extra-1391.png'],1476:['extra-1476.png'],751:['extra-751.png'],752:['extra-752.png'],753:['extra-753.png'],754:['extra-754.png']}
extra_ns=[216,218,220,221,222,228,503,504,561,562,633,634,775,776,1129,1130]
for j,n in enumerate(extra_ns):extra_evidence.setdefault(n,[]).append(f'bottom-extra-{j//4}.png')
def descriptor(n):
 return next((s for a,b,s in d['descriptors'] if a<=n<=b),'原生全景与球ROI已逐图检查')
out=[]
for n,r in enumerate(rows):
 meta=r['meta'];flags={k:meta[k] for k in tags};pending_scene=meta['scene_review_required']=='1';changes=d['flag_overrides'].get(str(n),{})
 if pending_scene:flags.update(changes)
 pending_label=meta['label_review_required']=='1'
 if not pending_label:ld='already_confirmed'
 elif n in positive:ld='approve_positive'
 elif n in negative:ld='approve_negative'
 else:ld='retain'
 if not pending_scene:sd='already_confirmed'
 elif n in sretain:sd='retain'
 elif ld.startswith('approve') or n in sapprove:sd='approve'
 else:sd='retain'
 evidence=[f'{D}/roi/page-{n//24:02d}.png'] if r['boxes'] else []
 if str(n) in nm:evidence.append(nm[str(n)])
 evidence += [D+'/native/'+f for f in extra_evidence.get(n,[])]
 if ld=='approve_negative':reason=negative_reasons[n]+'；空label确认为可见无球样本。'
 elif ld=='approve_positive':
  regions='；'.join(f'第{j+1}球位于原生x={b["xyxy"][0]:.1f}–{b["xyxy"][2]:.1f}, y={b["xyxy"][1]:.1f}–{b["xyxy"][3]:.1f}，可见范围{b["xyxy"][2]-b["xyxy"][0]:.1f}×{b["xyxy"][3]-b["xyxy"][1]:.1f}px' for j,b in enumerate(r['boxes']))
  reason=descriptor(n)+'；'+regions+'；球形外轮廓与白面板、深色星形/多边形花纹相符，现框四边覆盖完整可见球体，未把内部花纹、鞋、器材或投影另框；全景没有漏掉其他可见足球。'
  if n==138:reason+=' 另看原生5倍并列图，左侧深色球缘紧贴红框，约1–2px留边，四边可确认。'
 else:
  reason=descriptor(n)+'；'
  if ld=='already_confirmed':reason+='当前label已经审核确认，保留框和标注状态，仅审核尚未确认的场景。'
  else:reason+=d['retain'].get(str(n),'原生全景与ROI中球边界或可见性仍不够明确，保留审核。')+'；现label不通过，待进一步确认或修正。'
 if sd=='approve':
  actual=[]
  if flags['No Ball']=='1':actual.append('无可见足球，Small与Occluded为0')
  else:
   actual.append('Small='+flags['Small']+'（以672原生长边下完整球尺寸判断）')
   actual.append('Occluded='+flags['Occluded']+('，手、脚或器材明确盖住球缘' if flags['Occluded']=='1' else '，没有明确前景挡球'))
  actual.append('Blurred='+flags['Blurred']+('，球或整体画面可见拖影' if flags['Blurred']=='1' else '，未见球体或全图运动拖影'))
  reason+=' 场景通过：'+'；'.join(actual)+'。'
 elif sd=='retain':
  reason+=' 场景保留：'+('完整尺寸接近40px、球缘软化或遮挡/模糊边界不能可靠定；保留最合理现值或明确修正建议。' if n in sretain else '可见性、完整尺寸或遮挡与模糊程度仍有不确定性。')
 else:reason+=' 场景此前已确认，保留现有四项标记和审核状态。'
 if not pending_scene and changes and any(meta[k]!=v for k,v in changes.items()):reason+=' 本轮视觉发现分类疑点（建议'+','.join(k+'='+v for k,v in changes.items() if meta[k]!=v)+'），当前已确认场景未自动改写。'
 out.append({'filename':r['filename'],'index':r['index'],'scene_seen':True,'roi_seen':True if r['boxes'] else 'not_applicable','label_decision':ld,'scene_decision':sd,'flags':flags,'reason':reason,'native_evidence':evidence,'expected_label_sha256':r['label_sha256'],'expected_image_sha256':r['image_sha256'],'confidence_level':'uncertain' if ld=='retain' or sd=='retain' else 'high'})
json.dump(out,open(D+'/decisions.json','w'),ensure_ascii=False,indent=2)
summary={'items':len(out),'boxes':sum(len(r['boxes']) for r in rows),'label_decisions':dict(collections.Counter(x['label_decision'] for x in out)),'scene_decisions':dict(collections.Counter(x['scene_decision'] for x in out)),'opened_full_pages':d['opened_full'],'opened_roi_pages':d['opened_roi'],'opened_native':d['native_opened'],'negative_count':len(negative),'negative_native_evidence':{rows[n]['filename']:nm[str(n)] for n in negative},'scene_threshold':'完整最长边在原生长边672下约<=40px；约40px或完整尺寸不确定保留场景。','coverage':'所有1537张全景、所有1490框原生像素nearest放大ROI均实际打开。62张空label均再次原生全图查看，16页2×2每图672×376未缩放。额外4页完整底边2倍、原生4/5倍疑难图已实际打开。','production_files_modified':False}
json.dump(summary,open(D+'/summary.json','w'),ensure_ascii=False,indent=2)
json.dump(d,open(D+'/visual-notes.json','w'),ensure_ascii=False,indent=2)
print(json.dumps({k:summary[k] for k in ['items','boxes','label_decisions','scene_decisions']},ensure_ascii=False))
