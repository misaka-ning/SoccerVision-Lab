from common import *
from datetime import datetime,timezone
rows=load(ROOT/'analysis/source_inventory.json');segments=load(ROOT/'analysis/segments.json')
initial=load(ROOT/'analysis/initial_test_representatives.json');reviewed=load(ROOT/'analysis/pairs_to_visually_review.json')
for s in segments:
 if s['segment_id']=='S03':
  s['buffer_start_seconds']=265
  s['boundary_reason']+=' 补看N00250/N00255，4分38秒已是同一红衣人员连续机位；缓冲再提前至4分25秒，与S02后缓冲衔接，整段过渡不进入Train。'
 if s['segment_id']=='S05':s['test_status']='WITHDRAWN_PENDING_EVENT_REVIEW'
 else:s['test_status']='RETAIN_ELIGIBLE_REPRESENTATIVES'
 s['preferred_eye']='left' if int(s['segment_id'][1:])%2 else 'right'
withdrawn=[];final=[]
for r in initial:
 group='G02' if r['segment_id']=='S05' else 'G01' if r['segment_id']=='S01' and (r['seconds']<68 or r['seconds']>=103) else ''
 if group:withdrawn.append(dict(r,review_group=group))
 else:final.append(r)
groups=[dict(group_id='G01',segment_id='S01',reason='相机抬起前的固定机位及刚放下后的首批球/人物画面，仍与训练保留的前后过程有关；不依据低SSIM否认时序关联。保留中间明确搬动相机的负例过程，首尾代表图暂不入Test。',
    interval_rules='S01 core with time<68s or>=103s',evidence_pair_ids=['N00001','N00025','N00050','N00100'],
    disposition='heldout_unused',review_required_for_recovery=True,user_review_result=''),
 dict(group_id='G02',segment_id='S05',reason='已看N00026/N00043及片段联系图：远球/机器人位置接近，前景人员站立、俯身和离开有变化。无法明确分开同一机器人重置/球停留过程，整段候选暂不进Test；没有把背景相同直接认定为已确认重复。',
    interval_rules='S05 entire core644-670s',evidence_pair_ids=['N00026','N00027','N00043'],
    disposition='heldout_unused',review_required_for_recovery=True,user_review_result='')]
for g in groups:g['withdrawn_initial_representatives']=sum(r['review_group']==g['group_id'] for r in withdrawn)
observations=[]
native={'N00026','N00043','N00050','N00250'}
for p in reviewed:
 if p['segment_id']=='S01' and (p['test_seconds']<68 or p['test_seconds']>=103):
  assessment='uncertain_context_withdrawn';note=groups[0]['reason']
 elif p['segment_id']=='S05':assessment='uncertain_event_group_withdrawn';note=groups[1]['reason']
 elif p['segment_id']=='S03' and p['other_role']=='train' and p['other_seconds']<280:
  assessment='boundary_extended_opponent_now_buffer';note='红衣人员持控制器和白墙取景是连续机位，不能依赖cosine偏低认定无关联；已把4:25至原缓冲起点整体加入buffer。'
 elif p['other_role']=='val':
  assessment='different_confirmed_session_visually_distinct';note='实际对照能看到人体、机位/器材、球位置或纹理朝向的变化；用户已确认录像为不同场次。未据共同手臂/地面/玻璃门背景判为同一事件。'
 else:
  assessment='distinct_visible_states_no_confirmed_duplicate_event';note='已看对照：球的位置/纹理、前景鞋腿、机器人或取景存在明显变化，属于共同室内环境下不同可见状态。未见足以确认同一近重复事件的证据；保留同场次片段留出限制。'
 observations.append(dict(pair_id=p['pair_id'],test_image=p['test_image'],other_image=p['other_image'],
  actual_seen=True,view_method='4-pair contact grid, each scene336x188; native672x376 scene inspection additionally recorded where flagged',
  native_pair_opened=p['pair_id'] in native,evidence_path=p['evidence_path'],evidence_sha256=p['evidence_sha256'],
  assessment=assessment,assistant_observation=note,event_identity_confirmed=False,user_review_result=''))
save(ROOT/'analysis/pair_visual_observations_round1.json',observations)
save(ROOT/'analysis/uncertain_groups.json',groups);save(ROOT/'analysis/withdrawn_representatives.json',withdrawn)
save(ROOT/'analysis/final_test_representatives.json',final);save(ROOT/'analysis/segments.json',segments)
# Build complete source-time blocks; merged context is a conservative dependency group, not an independent session.
blocks=[]
for s in sorted(segments,key=lambda s:s['buffer_start_seconds']):
 if blocks and s['buffer_start_seconds']<=blocks[-1]['end_seconds']:
  blocks[-1]['end_seconds']=max(blocks[-1]['end_seconds'],s['buffer_end_seconds']);blocks[-1]['segments'].append(s['segment_id'])
 else:blocks.append(dict(start_seconds=s['buffer_start_seconds'],end_seconds=s['buffer_end_seconds'],segments=[s['segment_id']]))
for i,b in enumerate(blocks,1):b['block_id']=f'B{i:02d}';b['independent_event_count']=None
save(ROOT/'analysis/heldout_blocks.json',blocks)
selected={r['filename']:r for r in final};selected_frames={r['frame'] for r in final}
allocation=[]
for source in rows:
 if source['excluded']:continue
 r=dict(source);r['usage']='val' if r['source_split']=='val' else 'train';r['segment_id']='';r['heldout_block_id']='';r['review_group']=''
 r['reason']='Locked validation recording, user-confirmed independent session.' if r['usage']=='val' else 'Outside heldout cores and adaptive buffers.'
 if r['source']=='legacy':r['segment_id']='legacy_pooled_all';r['reason']='All713 legacy images stay Train as one conservative pooled group.'
 elif r['usage']=='val':r['segment_id']='val_'+r['source']+'_full'
 else:
  matched=[b for b in blocks if b['start_seconds']<=r['seconds']<=b['end_seconds']]
  cores=[s for s in segments if s['start_seconds']<=r['seconds']<=s['end_seconds']]
  if matched:
   r['heldout_block_id']=matched[0]['block_id']
   if cores:
    s=cores[0];r['segment_id']=s['segment_id'];r['usage']='test' if r['filename'] in selected else 'heldout_unused'
    r['reason']='Single-eye motion/state representative inside a wholly withheld core.' if r['usage']=='test' else 'Core retained outside training; thinning or unselected stereo eye.'
    if r['usage']=='heldout_unused' and r['frame'] in selected_frames:r['reason']='Other eye of a Test source-frame unit; not an independent Test sample.'
    if s['segment_id']=='S05':r['review_group']='G02'
    elif s['segment_id']=='S01' and (r['seconds']<68 or r['seconds']>=103):r['review_group']='G01'
    if r['review_group']:r['reason']='Conservative pending review '+r['review_group']+'; kept as heldout_unused, never returned to Train/Val.'
   else:r['usage']='buffer';r['segment_id']='buffer_'+matched[0]['block_id'];r['reason']='Adaptive boundary/continuous-action protection for '+','.join(matched[0]['segments'])+'.'
  else:
   gap=sum(r['seconds']>b['end_seconds'] for b in blocks);r['segment_id']=f'train_181531_gap{gap:02d}'
 r['eval_subset']='same_session_segment_holdout_v1' if r['usage']=='test' else ''
 allocation.append(r)
assert len(allocation)==8148 and sum(r['usage']=='val' for r in allocation)==1223
assert sum(r['source']=='legacy' and r['usage']=='train' for r in allocation)==713
assert len({r['frame'] for r in allocation if r['usage']=='test'})==len(final)
for b in blocks:assert not any(r['usage']=='train' and r['source']=='181531' and b['start_seconds']<=r['seconds']<=b['end_seconds'] for r in allocation)
save(ROOT/'analysis/allocation.json',allocation)
save(ROOT/'analysis/final_decision_summary.json',dict(roles=dict(Counter(r['usage'] for r in allocation)),
 test_flags={k:sum(r['flags'][k] for r in final) for k in FLAGS},withdrawn_representatives=len(withdrawn),groups=groups,
 candidate_core_segments=len(segments),test_segments=len({r['segment_id'] for r in final}),withheld_contiguous_blocks=len(blocks),
 test_physical_sessions=1,decision_timestamp_utc=datetime.now(timezone.utc).isoformat(),thresholds_are_not_truth=True))
print(json.dumps(load(ROOT/'analysis/final_decision_summary.json'),ensure_ascii=False,indent=2))
