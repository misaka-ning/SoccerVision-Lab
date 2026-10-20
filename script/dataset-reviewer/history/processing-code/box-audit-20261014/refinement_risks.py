#!/usr/bin/env python3
"""Rank visual-review hypotheses without approving any proposed football box."""
import argparse,collections,json
from pathlib import Path
from refine_boxes import protected_output,montage,dump

def build(rows):
    risks=[]
    for r in rows:
        o=r['original_xyxy']; p=r['xyxy']; w=o[2]-o[0]; h=o[3]-o[1]
        ev=r.get('evidence',{}); ratio=ev.get('area_ratio',1.); flags=r['flags']; labels=[]; score=0.
        side=[(p[0]-o[0])/max(1,w),(p[1]-o[1])/max(1,h),(o[2]-p[2])/max(1,w),(o[3]-p[3])/max(1,h)]
        if min(side)>-.04 and sum(max(0,s) for s in side)>.23:
            labels.append('possible_excess_border_gap'); score+=2
        if 'original_box_may_cover_only_part_of_ball' in flags or 'crop_detector_suggests_original_partial_or_misplaced_box' in flags:
            labels.append('possible_partial_or_shifted_original_box'); score+=4
        if 'edge_fit_disagrees_with_semantic_crop_detection' in flags:
            labels.append('geometric_and_semantic_candidates_disagree'); score+=3
        if 'large_motion_or_size_change' in flags:
            labels.append('large_change_needs_visual_review'); score+=3
        if 'image_edge_clipped' in flags:
            labels.append('visible_extent_at_image_edge'); score+=1
        if 'occluded_visible_extent_requires_manual_review' in flags:
            labels.append('visible_extent_under_occlusion'); score+=1.5
        if ratio<.62:
            labels.append('possible_internal_panel_fit_or_grossly_loose_original'); score+=3
        if r['fit_confidence']<.35:
            labels.append('boundary_evidence_is_weak_or_unresolved'); score+=.5
        if r.get('is_human_provided_annotation'):
            labels.append('human_annotation_preserve_and_review_proposal'); score+=.1
        risks.append({'filename':r['filename'],'image_path':r['image_path'],'box_index':r['box_index'],
            'inventory_box_index':r.get('inventory_box_index'),'risk_score':round(score,3),'review_topics':labels,
            'original_xyxy':o,'candidate_xyxy':p,'fit_confidence':r['fit_confidence'], 'fit_confidence_is_calibrated_probability':False,
            'evidence':ev,'candidate_status':'pending_visual_review','automatically_approved':False,
            'annotation_status_before':r.get('annotation_status_before'),'is_human_provided_annotation':r.get('is_human_provided_annotation',False),
            'crop_detector_agreement_iou':r.get('crop_detector_agreement_iou'),'crop_detector_max_related_confidence':r.get('crop_detector_max_related_confidence'),
            'crop_detection_proposals':r.get('crop_detection_proposals',[]),'flags':flags})
    return sorted(risks,key=lambda r:(-r['risk_score'],r['filename'],r['box_index']))

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--input',required=True,type=Path); p.add_argument('--output',required=True,type=Path);p.add_argument('--top-montage',type=Path);p.add_argument('--top',type=int,default=144);a=p.parse_args();rows=json.loads(a.input.read_text()); risks=build(rows);dump(a.output,risks)
    summary={'boxes':len(risks),'images':len(set(x['filename'] for x in risks)), 'topics':dict(collections.Counter(t for r in risks for t in r['review_topics'])), 'all_pending_review':True,'no_model_only_approval':True,'source':str(a.input.resolve())}; dump(a.output.with_name(a.output.stem+'-summary.json'),summary)
    if a.top_montage:
        bykey={(r['filename'],r['box_index']):r for r in rows}; chosen=[bykey[(r['filename'],r['box_index'])] for r in risks[:a.top]]; montage(chosen,protected_output(a.top_montage))
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__': main()
