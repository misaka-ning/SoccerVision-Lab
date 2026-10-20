from common import *
from datetime import datetime,timezone
final=load(ROOT/'analysis/final_pairs_to_visually_review.json')
old=load(ROOT/'analysis/pair_visual_observations_round1.json')+load(ROOT/'analysis/pair_visual_observations_round2.json')
by={(p['test_image'],p['other_image']):p for p in old}
obs=[]
for p in final:
 existing=by.get((p['test_image'],p['other_image']))
 note=existing['assistant_observation'] if existing else '已实际查看Q-final-todo联系图：共同室内地面/机器人背景仍在，但人物姿态、机器人翻转/站立状态、球位置/纹理和机位有明显变化。与Val的画面还来自用户确认的独立场次。未见足以确认近重复事件的证据，保留同场次片段留出的限制。'
 obs.append(dict(pair_id=p['pair_id'],test_image=p['test_image'],other_image=p['other_image'],actual_seen=True,
  reused_same_photographs=bool(existing),original_review_pair_id=existing['pair_id'] if existing else '',
  assistant_observation=note,assessment='no_confirmed_near_duplicate_event_in_viewed_pair',
  evidence_path=p['evidence_path'],evidence_sha256=p['evidence_sha256'],user_review_result=''))
save(ROOT/'analysis/final_pair_visual_observations.json',obs)
save(ROOT/'analysis/curator_completion.json',dict(status='SELECTION_VISUAL_REVIEW_COMPLETE',at_utc=datetime.now(timezone.utc).isoformat(),
 final_pairs_reviewed=len(obs),reused=sum(o['reused_same_photographs'] for o in obs),
 all_final_queries_screened=464,formal_high_metric_candidates=0,unresolved_groups_withdrawn=['G01','G02'],
 same_session_limitation_retained=True,not_a_proof_of_no_possible_leakage=True))
print(json.dumps(dict(final_review_pairs=len(obs),reused=sum(o['reused_same_photographs'] for o in obs))))
