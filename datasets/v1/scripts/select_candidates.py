from common import *

def main():
 rows=load(ROOT/'analysis/source_inventory.json');active=[r for r in rows if not r['excluded']]
 segments=load(ROOT/'analysis/draft_segments.json')
 adjustments={'S01':{'start_seconds':64},'S02':{'end_seconds':259},
  'S03':{'start_seconds':280,'buffer_start_seconds':265},'S04':{'end_seconds':600,'buffer_start_seconds':486,'buffer_end_seconds':610},
  'S06':{'end_seconds':789,'buffer_start_seconds':733},'S07':{'end_seconds':1162},
  'S08':{'buffer_start_seconds':1447,'buffer_end_seconds':1540}}
 notes={
 'S01':'已看联系图：64秒人员走近后开始搬动相机；延续至放回低机位，后缓冲覆盖放置后球进入近处过程。62秒静止视图不选Test。',
 'S02':'已看联系图：预缓冲含从站立低头至首次接球；后缓冲含最后滚球和抬头转向货架，避免只截取滚球中段。',
 'S03':'已看联系图与N00250/N00255：红衣人员持控制器机位更早建立，核心扩展含280秒之后完整准备阶段；预缓冲从265秒开始与S02衔接，后缓冲保留到转向较远球。',
 'S04':'已看联系图及F00014/F00019/F00034/F00420/F01425：09:19和10:00仍属同一连续跟球取景。整段08:06-10:10移出Train，核心覆盖08:24-10:00完整远球阶段，末尾缓冲至转向玻璃门，避免用视觉差异推断独立。',
 'S05':'已看联系图：预缓冲包含朝空地转向和远球进入；后缓冲含前景人员俯身处理机器人并离开的尾部。',
 'S06':'已看联系图：12分20秒前球已开始运动，预缓冲扩大到12分13秒转向前；后缓冲到再次抬头面向货架。',
 'S07':'已看联系图：始于货架旁取景回到球与脚部，后缓冲覆盖球到门口及抬头；19分27秒之后是新的人物持球取景。',
 'S08':'已看联系图：24分12秒远球已经可见，预缓冲提前到24分07秒；25分33-37秒仍有远球跟随，后缓冲继续到25分40秒对准货架且无球，覆盖完整尾部。',
 'S09':'已看联系图：预缓冲包含离场前机位抬起和步行开始，核心覆盖玻璃门及外侧地面，直到录像结束。',
 }
 for s in segments:
  s.update(adjustments.get(s['segment_id'],{}));s['status']='CONTACT_SHEET_VISUALLY_REVIEWED'
  s['boundary_reason']=notes[s['segment_id']]
  s['preferred_eye']='left' if int(s['segment_id'][1:])%2 else 'right'
  s['event_group_id']='event_chain_'+s['segment_id']
  s['independent_event_count']=None
  s['visual_evidence_read']='evidence/draft-'+s['segment_id']+'.jpg'
  s['reviewed_page_sha256']=sha(ROOT/s['visual_evidence_read'])
 features=np.load(AUDIT/'data/embeddings.npz');fv={int(i):v for i,v in zip(features['indices'],features['features'])}
 gray=np.load(AUDIT/'data/gray128x72.npz')['gray']
 all_candidates=[];selected=[];selection_log=[];pages=[]
 for s in segments:
  inside=[r for r in active if r['source']=='181531' and s['start_seconds']<=r['seconds']<=s['end_seconds']]
  groups=defaultdict(list)
  for r in inside:groups[r['frame']].append(r)
  choices=[]
  for frame,rr in sorted(groups.items()):
   r=dict(next((r for r in rr if r['eye']==s['preferred_eye']),rr[0]));r.update(segment_id=s['segment_id'],event_group_id=s['event_group_id'])
   choices.append(r)
  kept=[]
  for r in choices:
   decision='segment_first_representative'
   if kept:
    prev=kept[-1];dt=r['seconds']-prev['seconds'];c=float(fv[r['index']]@fv[prev['index']]);v=ssim(gray[r['index']],gray[prev['index']])
    pd=(int(r['phash'],16)^int(prev['phash'],16)).bit_count();dd=(int(r['dhash'],16)^int(prev['dhash'],16)).bit_count()
    flags_changed=r['flags']!=prev['flags'];both_neg=r['flags']['No Ball'] and prev['flags']['No Ball']
    geom=1.0
    if len(r['boxes'])==len(prev['boxes']) and r['boxes']:
     aa=np.array(sorted(b[1:] for b in r['boxes']));bb=np.array(sorted(b[1:] for b in prev['boxes']));geom=float(np.abs(aa-bb).max())
    if both_neg:geom=0
    very_similar=c>=.985 and v>=.88 and pd<=8 and dd<=10 and geom<.035 and not flags_changed
    still=c>=.97 and v>=.77 and geom<.035 and not flags_changed
    rapid_change=c<.93 and v<.70
    if dt<.45:decision='skip_dense_timestamp'
    elif very_similar and dt<8:decision='skip_joint_near_identical_representative'
    elif still and dt<3:decision='skip_redundant_local_state'
    elif both_neg and dt<1.2 and not (rapid_change and dt>=.7):decision='skip_dense_negative'
    elif not both_neg and dt<.85 and not (flags_changed or rapid_change or geom>.065):decision='skip_dense_unchanged_ball_state'
    else:decision='retain_changed_state_or_spaced_representative'
    selection_log.append(dict(filename=r['filename'],segment_id=s['segment_id'],previous=prev['filename'],seconds_delta=dt,
     cosine=c,ssim=v,phash_distance=pd,dhash_distance=dd,max_bbox_component_delta=geom,decision=decision))
   if not decision.startswith('skip'):kept.append(r)
  s['core_images']=len(inside);s['core_source_moments']=len(choices);s['initial_representatives']=len(kept)
  all_candidates.extend(choices);selected.extend(kept)
  context=[r for r in active if r['source']=='181531' and s['buffer_start_seconds']<=r['seconds']<=s['buffer_end_seconds']]
  groups2=defaultdict(list)
  for r in context:groups2[r['frame']].append(r)
  timeline=[next((r for r in rr if r['eye']==s['preferred_eye']),rr[0]) for _,rr in sorted(groups2.items())]
  shown=[]
  for t in np.arange(s['buffer_start_seconds'],s['buffer_end_seconds']+.1,3):
   r=dict(min(timeline,key=lambda r:abs(r['seconds']-t)))
   if shown and shown[-1]['frame']==r['frame']:continue
   r['display_role']='CORE' if s['start_seconds']<=r['seconds']<=s['end_seconds'] else 'BUFF';shown.append(r)
  pages.append(contact(shown,ROOT/f'evidence/segment-{s["segment_id"]}.jpg',f'{s["segment_id"]} final holdout core and adaptive buffers / one physical session',cols=6,tile_w=224,tile_h=126))
 roles=Counter()
 for r in active:
  role='val' if r['source_split']=='val' else 'train'
  if r['source']=='181531':
   for s in segments:
    if s['buffer_start_seconds']<=r['seconds']<=s['buffer_end_seconds']:
     role='heldout_unused' if s['start_seconds']<=r['seconds']<=s['end_seconds'] else 'buffer';break
  roles[role]+=1
 roles['heldout_unused']-=len(selected);roles['test']=len(selected)
 save(ROOT/'analysis/segments.json',segments);save(ROOT/'analysis/core_eye_candidates.json',all_candidates)
 save(ROOT/'analysis/initial_test_representatives.json',selected);save(ROOT/'analysis/sampling_decisions.json',selection_log)
 save(ROOT/'analysis/segment_contact_pages.json',pages)
 save(ROOT/'analysis/initial_selection_summary.json',dict(assignments=dict(roles),eye_rule='Fixedleft for odd segment IDs, right for even; fallback only when preferred eye is excluded/missing. No quality/confidence/label-based eye choice.',
  quotas='400-600 is an engineering reference, no forced fill; adaptive local multi-signal temporal thinning applied first.',
  initial_test_flags={k:sum(r['flags'][k] for r in selected) for k in FLAGS},seed=SEED,
  thresholds_are_independence_proof=False))
 print(json.dumps(dict(initial_roles=roles,initial_test_flags={k:sum(r['flags'][k] for r in selected) for k in FLAGS},segments=[(s['segment_id'],s['core_images'],s['initial_representatives']) for s in segments]),ensure_ascii=False))

if __name__=='__main__':main()
