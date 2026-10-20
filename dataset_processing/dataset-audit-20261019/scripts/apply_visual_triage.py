"""Promote audit-only review priority using recorded visual observations.

This modifies audit CSV/JSON only. It never labels a capture event as confirmed
from image similarity, and never changes source images, labels or split fields.
"""
import ast,csv,hashlib,json
from collections import Counter
from pathlib import Path
R=Path(__file__).resolve().parents[1]
p=R/'data/similarity-pairs.json';pairs=json.loads(p.read_text())
medium=json.loads((R/'data/medium-pair-visual-review.json').read_text())['records']
observations={r['pair_id']:r for r in medium}
assert len(observations)==16 and all(r['review_status']=='' and r['actual_visual_seen'] for r in medium)
visual=json.loads((R/'data/legacy-pair-visual-review.json').read_text())
temporal=json.loads((R/'data/root-temporal-visual-review.json').read_text())
assert len(visual)==26 and all(r['actual_opened_evidence']['opened'] and r['review_status']=='' for r in visual)
assert len(temporal)==8 and all(r['review_status']=='' and Path(r['actual_opened_evidence']).is_file() for r in temporal)
seen={r['pair_id']:r for r in visual+temporal+medium}
assert len(seen)==50
for r in pairs:
    r.setdefault('automated_risk_level',r['risk_level'])
    r['risk_level']=r['automated_risk_level']
    r['assistant_visual_reviewed']=r['pair_id'] in seen
    r['assistant_visual_observation']=seen.get(r['pair_id'],{}).get('assistant_observation','')
    r['assistant_visual_assessment']=seen.get(r['pair_id'],{}).get('visual_assessment','')
    if r['pair_id'] in observations:
        assert observations[r['pair_id']]['visual_assessment']=='v_near_duplicate'
        r['risk_level']='high'
        r['assessment_status']='assistant_visual_near_duplicate_risk_event_unconfirmed'
        r['recommended_review_reason']='人工查看原图对照发现主体、球纹/手部和物件布局高度接近；SSIM较低不排除位移近重复。采集事件/场次仍未确认，不自动判科研泄漏。'
        r['assistant_visual_observation']=observations[r['pair_id']]['assistant_observation']
        r['review_status']=''
p.write_text(json.dumps(pairs,ensure_ascii=False,indent=2)+'\n')
tree=ast.parse((R/'scripts/similarity_audit.py').read_text());cols=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='cols' for t in n.targets)))
cols+=['automated_risk_level','assistant_visual_reviewed','assistant_visual_observation','assistant_visual_assessment']
with (R/'cross_split_duplicates.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(pairs)
s=dict(candidate_pairs=len(pairs),automated_risk_counts=dict(Counter(r['automated_risk_level'] for r in pairs)),
       final_review_priority_counts=dict(Counter(r['risk_level'] for r in pairs)),
       visual_review_promotions=len(medium),legacy_high_reviewed=len(visual),
       legacy_visual_near_supported=sum(r['visual_assessment']=='visual_near_duplicate_confirmed' for r in visual),
       legacy_visual_uncertain=sum(r['visual_assessment']!='visual_near_duplicate_confirmed' for r in visual),
       medium_visual_near_supported=len(medium),source_event_confirmation_from_legacy_images=0,
       actual_visual_reviewed_pairs=len(seen),temporal_representatives_actually_viewed=len(temporal),
       confirmed_file_or_pixel_duplicates=sum(r['exact_match'] or r['pixel_exact_match'] for r in pairs),
       review_status_all_blank=all(r['review_status']=='' for r in pairs),
       source_modified=False,split_pair_counts={})
for a,b in [('train','val'),('train','test'),('val','test')]:
    q=[r for r in pairs if {r['split_a'],r['split_b']}=={a,b}]
    s['split_pair_counts'][a+'-'+b]=dict(final_priority=dict(Counter(r['risk_level'] for r in q)),
        automated_priority=dict(Counter(r['automated_risk_level'] for r in q)),
        high_both_usable=sum(r['risk_level']=='high' and r['both_usable'] for r in q))
(R/'data/final-triage-summary.json').write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(s,ensure_ascii=False,indent=2))
