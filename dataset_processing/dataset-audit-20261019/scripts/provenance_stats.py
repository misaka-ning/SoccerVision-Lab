#!/usr/bin/env python3
"""Read-only provenance recovery, temporal overlap and descriptive split statistics.

Writes only into this audit directory. Historical image/media files are not read.
Historical manifests are trusted only after current image SHA256 equality.
"""
from __future__ import annotations
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import re

BASE = Path('/home/misaka/workspace/dataset_processing/dataset-audit-20261019')
HISTORY = Path('/home/misaka/temp/dataset-curation-20261013')
FLAGS = ['Small', 'Occluded', 'Blurred', 'No Ball']
SPLITS = ['train', 'val', 'test']
THRESHOLDS = [1, 5, 15, 30, 75, 150]
SOURCES = {
 '104748': HISTORY / 'restructured-manifest.jsonl',
 '104748_summary': HISTORY / 'football_20261013_104748_before_restructure/summary.json',
 'restructure_summary': HISTORY / 'restructure-summary.json',
 'legacy': HISTORY / 'legacy-merge/imported-manifest.jsonl',
 'legacy_summary': HISTORY / 'legacy-merge/merge-summary.json',
 '181531_trim': Path('/home/misaka/temp/nvidia-recordings-20261013-181531/trim-report.json'),
 '181326_addition': HISTORY / 'reaudit-20261013-205545/evidence/new-recording/addition-manifest.json',
 '181326_selection': Path('/home/misaka/temp/nvidia-recordings-20261013-193624/curated-video-report.json'),
}

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def load(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))

def save(p, d):
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def wilson(k, n, z=1.959963984540054):
    if not n:
        return None
    p=k/n; den=1+z*z/n
    center=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [max(0.,center-half),min(1.,center+half)]

def n_worst(margin):
    # Conservative normal binomial planning, rather than a claim of actual power.
    return math.ceil(1.959963984540054**2*.25/margin**2)

def size_stats(items):
    # Geometric bins describe labels; they do not diagnose semantic Small.
    maxbins=Counter(); areabins=Counter(); nativeareas=Counter(); n=0
    for item in items:
        w,h=item['width'],item['height']
        scale=672/max(w,h)
        for box in item['boxes']:
            bw,bh=box['xywhn'][2]*w,box['xywhn'][3]*h
            longest=max(bw,bh)*scale; area=bw*bh*scale*scale
            maxbins['<=16' if longest<=16.00001 else '(16,32]' if longest<=32.00001 else '(32,40]' if longest<=40.00001 else '(40,64]' if longest<=64.00001 else '(64,96]' if longest<=96.00001 else '>96']+=1
            areabins['<32^2' if area<32**2 else '[32^2,96^2)' if area<96**2 else '>=96^2']+=1
            na=bw*bh
            nativeareas['<32^2' if na<32**2 else '[32^2,96^2)' if na<96**2 else '>=96^2']+=1
            n+=1
    return {'boxes':n,'longest_side_at_672_px':dict(maxbins),'bbox_area_at_672_px2':dict(areabins),'native_bbox_area_px2':dict(nativeareas)}

def describe(items, records):
    yes=[x for x in items if x['usable']]
    out={'all_images':len(items),'usable_images':len(yes),'excluded_images':len(items)-len(yes),
         'positive_images':sum(bool(x['boxes']) for x in yes),'negative_images':sum(not x['boxes'] for x in yes),
         'boxes':sum(len(x['boxes']) for x in yes),
         'joint_flags_order':FLAGS,'joint_flags_usable':dict(Counter(''.join(x['meta'][f] for f in FLAGS) for x in yes)),
         'geometry_usable':size_stats(yes)}
    out['scenarios']={}
    for f in FLAGS:
        rr=[x for x in yes if x['meta'][f]=='1']
        pos=[x for x in rr if x['boxes']]
        groups={(records[x['filename']]['recording_id'],records[x['filename']]['source_frame_idx']) for x in pos if records[x['filename']]['recording_id'] and records[x['filename']]['source_frame_idx'] is not None}
        timelines=defaultdict(set)
        for x in pos:
            rec=records[x['filename']]
            if rec['recording_id'] and rec['source_frame_idx'] is not None:
                timelines[rec['recording_id']].add(rec['source_frame_idx'])
        timeline_stats={}
        for rid,frames in timelines.items():
            frame_list=sorted(frames)
            rec=next(records[x['filename']] for x in pos if records[x['filename']]['recording_id']==rid)
            fps=rec['fps']
            timeline_stats[rid]={'positive_frames':frame_list,'first_frame':frame_list[0],'last_frame':frame_list[-1],
                                 'span_seconds':(frame_list[-1]-frame_list[0])/fps if fps else None,'fps':fps}
        out['scenarios'][f]={'images':len(rr),'positive_images':len(pos),'boxes':sum(len(x['boxes']) for x in pos),
              'negative_images':len(rr)-len(pos),'confirmed_recording_frame_groups_positive':len(groups),
              'positive_images_without_frame_identity':sum(records[x['filename']]['source_frame_idx'] is None for x in pos),
              'positive_recording_timelines':timeline_stats,
              'box_count_interpretation':'All valid football boxes in images carrying this scene flag. Metadata has no instance-level flags; in multi-ball images this does not prove every box has the attribute.'}
    known={records[x['filename']]['recording_id'] for x in yes if records[x['filename']]['recording_id']}
    out['confirmed_recording_ids']=sorted(known)
    out['confirmed_recording_count']=len(known)
    out['images_unknown_physical_session']=len(yes)
    out['images_unknown_recording']=sum(not records[x['filename']]['recording_id'] for x in yes)
    out['independent_session_count']=None
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--inventory', type=Path, default=BASE/'data/inventory.json'); args=ap.parse_args()
    inv=load(args.inventory)
    hist={r['filename']:r for r in map(json.loads,SOURCES['104748'].read_text().splitlines())}
    legacy={r['merged_filename']:r for r in map(json.loads,SOURCES['legacy'].read_text().splitlines())}
    add={r['图片']:r for r in load(SOURCES['181326_addition'])}
    summary=load(SOURCES['104748_summary']); trim=load(SOURCES['181531_trim']); sel=load(SOURCES['181326_selection'])
    evidence={k:{'path':str(p),'sha256':digest(p),'bytes':p.stat().st_size} for k,p in SOURCES.items()}
    records={}; mismatch=[]
    for x in inv:
        name=x['filename']; m=x['meta']
        r={'filename':name,'index':x['index'],'split':x['split'],'usable':x['usable'],'image_sha256':x['image_sha256'],
          'recording_id':None,'source_video':None,'source_frame_idx':None,'eye':None,'fps':None,'source_seconds':None,
          'physical_session_id':None,'physical_session_confidence':'unknown','provenance_confidence':'unknown',
          'association_level':'unknown','evidence_paths':[],'evidence_rule':'No reliable physical recording identity; numeric filename is not sufficient.'}
        if m.get('source_video') and m.get('source_frame_idx')!='' and m.get('eye'):
            frame=int(m['source_frame_idx']); source=m['source_video']; eye=m['eye']
            r.update(recording_id=Path(source).stem,source_video=source,source_frame_idx=frame,eye=eye,
                     provenance_confidence='confirmed_metadata_and_consistent_filename',association_level='confirmed',
                     evidence_paths=['/home/misaka/workspace/datasets/metadata.csv'])
            if 'first27min' in source:
                pat=re.fullmatch(r'video_([a-f0-9]{16})_frame_(\d+)_(left|right)\.png',name)
                if not pat or pat[1]!=trim['video_sha256'][:16] or int(pat[2])!=frame or pat[3]!=eye:
                    mismatch.append({'filename':name,'reason':'metadata/frame filename or historical video hash prefix mismatch'})
                r.update(fps=trim['fps'],evidence_rule='Current source_video/frame/eye agree with filename; video hash prefix agrees with historical lossless trim report.',
                         evidence_paths=r['evidence_paths']+[str(SOURCES['181531_trim'])])
            else:
                a=add.get(name)
                if a and a['image_sha256']==x['image_sha256']:
                    r.update(provenance_confidence='confirmed_sha256_historical_manifest',fps=sel['fps'],
                             evidence_rule='Current image bytes SHA256 equal historical addition manifest; frame and eye agree with current metadata.',
                             evidence_paths=r['evidence_paths']+[str(SOURCES['181326_addition']),str(SOURCES['181326_selection'])])
                else:
                    mismatch.append({'filename':name,'reason':'addition manifest image SHA256 mismatch or missing'})
        elif name in hist:
            h=hist[name]
            if h['png_sha256']==x['image_sha256']:
                r.update(recording_id=Path(summary['source_video']).stem,source_video=summary['source_video'],source_frame_idx=h['frame_idx'],eye=h['eye'],
                         fps=summary['source_fps'],source_seconds=h['video_time_seconds'],
                         historical_original_timestamp=h.get('original_timestamp'),historical_clip_id=h.get('clip_id'),historical_temporal_group_id=h.get('temporal_group_id'),
                         provenance_confidence='confirmed_sha256_historical_manifest',association_level='confirmed',
                         evidence_paths=[str(SOURCES['104748']),str(SOURCES['104748_summary'])],
                         evidence_rule='Current image bytes SHA256 equal historical png_sha256; filename uniquely maps to historical source_video/frame/eye/seconds. Original timestamp units/clock are not reinterpreted.')
            else:
                mismatch.append({'filename':name,'reason':'historical plain-frame manifest current image SHA256 mismatch'})
        elif name in legacy:
            h=legacy[name]
            if h['image_sha256']==x['image_sha256']:
                r.update(legacy_original_path=h['image_path'],legacy_original_split=h['split'],
                         provenance_confidence='confirmed_original_file_identity_recording_unknown',
                         evidence_paths=[str(SOURCES['legacy'])],
                         evidence_rule='Current image SHA256 equals legacy import manifest; original split/path recovered. Numeric file stems are not video frame IDs; true recording/session remains unknown.')
            else:
                mismatch.append({'filename':name,'reason':'historical legacy image SHA256 mismatch'})
        if r['fps'] and r['source_seconds'] is None:
            r['source_seconds']=r['source_frame_idx']/r['fps']
        records[name]=r

    invby={x['filename']:x for x in inv}
    byrecording=defaultdict(list)
    for name,r in records.items():
        if r['recording_id']:
            byrecording[r['recording_id']].append(invby[name])
    recording_summary={k:describe(v,records) for k,v in byrecording.items()}
    for k,v in byrecording.items():
        recording_summary[k]['all_split_counts']=dict(Counter(x['split'] for x in v))
        recording_summary[k]['usable_split_counts']=dict(Counter(x['split'] for x in v if x['usable']))
    # Filename stereo partners are safe within a shared stem even without source video.
    stereo=defaultdict(list)
    for x in inv:
        r=records[x['filename']]
        if r['recording_id']:
            stereo[('known',r['recording_id'],r['source_frame_idx'])].append(x)
        elif re.search(r'_(left|right)\.[^.]+$',x['filename']):
            stereo[('filename_only',re.sub(r'_(left|right)(?=\.[^.]+$)','',x['filename']))].append(x)
    sameframe_cross=[]
    for key,xs in stereo.items():
        if len({x['split'] for x in xs})>1:
            sameframe_cross.append({'key':key,'filenames':[x['filename'] for x in xs],'splits':sorted({x['split'] for x in xs})})

    # All-split nearest-time image pairs and all pairs within explicit frame thresholds.
    pairs={}; temporal={}; run_summary=[]
    for rid,xs in byrecording.items():
        groups=defaultdict(lambda:defaultdict(list))
        for x in xs:
            if x['usable']:
                groups[x['split']][records[x['filename']]['source_frame_idx']].append(x)
        for sa,sb in itertools.combinations(SPLITS,2):
            ga,gb=groups[sa],groups[sb]
            if not ga or not gb:
                continue
            fa,fb=sorted(ga),sorted(gb); fps=records[xs[0]['filename']]['fps']
            nearest=set()
            for aa,bb,A,B,reverse in [(fa,fb,ga,gb,False),(fb,fa,gb,ga,True)]:
                for f in aa:
                    j=bisect_left(bb,f); candidates=bb[max(0,j-1):min(len(bb),j+1)]
                    dist=min(abs(f-g) for g in candidates)
                    for g in candidates:
                        if abs(f-g)==dist:
                            nearest.add((g,f) if reverse else (f,g))
            for f,g in nearest:
                for a,b in itertools.product(ga[f],gb[g]):
                    key=(a['filename'],b['filename'])
                    pairs[key]={'index_a':a['index'],'index_b':b['index'],'image_a':a['filename'],'image_b':b['filename'],
                       'image_path_a':a['image_path'],'image_path_b':b['image_path'],'split_a':sa,'split_b':sb,
                       'source_video':records[a['filename']]['source_video'],'recording_id':rid,'frame_a':f,'frame_b':g,
                       'delta_frames':abs(f-g),'fps':fps,'delta_seconds':abs(f-g)/fps if fps else '',
                       'eye_a':records[a['filename']]['eye'],'eye_b':records[b['filename']]['eye'],
                       'association_level':'confirmed_same_recording','risk_level':'high_temporal' if abs(f-g)<=15 else 'review_temporal' if abs(f-g)<=150 else 'shared_recording_only',
                       'is_nearest_time_candidate':True,'evidence_a':';'.join(records[a['filename']]['evidence_paths']),
                       'evidence_b':';'.join(records[b['filename']]['evidence_paths']),'sha256_a':a['image_sha256'],'sha256_b':b['image_sha256'],
                       'review_status':'','note':'Shared recording is confirmed; near time is risk evidence, not automatic pixel/semantic duplicate adjudication.'}
            count={}
            for t in THRESHOLDS:
                ng=0; ni=0; touched=set()
                for f in fa:
                    for g in fb[bisect_left(fb,f-t):bisect_right(fb,f+t)]:
                        ng+=1;ni+=len(ga[f])*len(gb[g]);touched.update(x['filename'] for x in ga[f]+gb[g])
                count[str(t)]={'unique_frame_pairs':ng,'image_pairs':ni,'affected_images':len(touched)}
            min_delta=min(abs(f-g) for f,g in nearest)
            temporal[f'{rid}|{sa}-{sb}']={'minimum_delta_frames':min_delta,'fps':fps,'minimum_delta_seconds':min_delta/fps if fps else None,
                     'threshold_counts':count,'nearest_image_pairs':sum(1 for p in pairs.values() if p['recording_id']==rid and p['split_a']==sa and p['split_b']==sb)}
        allf=defaultdict(list)
        for x in xs:
            if x['usable']:
                allf[records[x['filename']]['source_frame_idx']].append(x)
        for maxgap in [15,75,150]:
            runs=[]; run=[]
            for f in sorted(allf):
                if run and f-run[-1]>maxgap:
                    runs.append(run);run=[]
                run.append(f)
            if run:runs.append(run)
            for run in runs:
                rr=[x for f in run for x in allf[f]]
                ss=Counter(x['split'] for x in rr)
                if len(ss)>1:
                    run_summary.append({'recording_id':rid,'max_observed_frame_gap':maxgap,'start_frame':run[0],'end_frame':run[-1],
                              'sampled_times':len(run),'images':len(rr),'split_counts':dict(ss),'interpretation':'Operational temporal run; no claim that scene content was continuously unchanged.'})

    boundary_budget={}
    for t in THRESHOLDS:
        affected_train=set();affected_eval=set()
        for rid,xs in byrecording.items():
            ee=sorted((records[x['filename']]['source_frame_idx'],x['filename']) for x in xs if x['usable'] and x['split']!='train')
            ff=[x[0] for x in ee]
            for x in xs:
                if not x['usable'] or x['split']!='train':continue
                f=records[x['filename']]['source_frame_idx']
                neighbors=ee[bisect_left(ff,f-t):bisect_right(ff,f+t)]
                if neighbors:
                    affected_train.add(x['filename']);affected_eval.update(n for _,n in neighbors)
        boundary_budget[str(t)]={'candidate_train_images_to_quarantine':len(affected_train),'remaining_train_images':sum(x['usable'] and x['split']=='train' for x in inv)-len(affected_train),'affected_eval_images':len(affected_eval),'candidate_train_filenames':sorted(affected_train),'note':'Planning candidate only; frame threshold does not prove all visual or event leakage is eliminated.'}
    similarity_plan=None
    similarity_path=BASE/'data/similarity-pairs.json'
    if similarity_path.exists():
        similarity=load(similarity_path)
        high=[p for p in similarity if p['risk_level']=='high' and p.get('both_usable')]
        temporal_high=[p for p in high if p.get('same_recording') and p.get('delta_seconds') is not None and p['delta_seconds']<=1]
        temporal_ids={p['pair_id'] for p in temporal_high}
        visual_high=[p for p in high if p['pair_id'] not in temporal_ids]
        def split_names(pp,split):
            return {p['filename_'+side] for p in pp for side in ['a','b'] if p['split_'+side]==split}
        def train_names(pp):
            return split_names(pp,'train')
        tt,vv=train_names(temporal_high),train_names(visual_high)
        vt=[p for p in high if {p['split_a'],p['split_b']}=={'val','test'}]
        vtval,vttest=split_names(vt,'val'),split_names(vt,'test')
        automated=[p for p in similarity if p.get('automated_risk_level',p['risk_level'])=='high' and p.get('both_usable')]
        automatic_train=train_names(automated)
        pair_key=lambda p:'-'.join(sorted([p['split_a'],p['split_b']],key=SPLITS.index))
        similarity_plan={'source_path':str(similarity_path),'source_sha256':digest(similarity_path),'candidate_pairs_all':len(similarity),
          'high_pairs':len(high),'confirmed_temporal_adjacency_pairs':len(temporal_high),'visual_high_risk_pairs_source_unknown':len(visual_high),
          'high_split_pair_counts':dict(Counter(pair_key(p) for p in high)),
          'temporal_train_images':len(tt),'visual_train_images':len(vv),'train_intersection':sorted(tt&vv),'train_union_images':len(tt|vv),
          'candidate_train_filenames':sorted(tt|vv),'temporal_train_filenames':sorted(tt),'visual_train_filenames':sorted(vv),
          'proposed_counts_if_all_high_train_sides_quarantined':{'train':7857-len(tt|vv),'val':164,'test':127,'total':8148-len(tt|vv)},
          'train_only_does_not_resolve_val_test_pairs':len(vt),
          'val_test_risk_pairs':[p['pair_id'] for p in vt],
          'proposed_preserve_test':{'candidate_train_filenames':sorted(tt|vv),'candidate_val_filenames':sorted(vtval),
             'additional_eval_candidates':len(vtval),'counts':{'train':7857-len(tt|vv),'val':164-len(vtval),'test':127,'total':8148-len(tt|vv)-len(vtval)}},
          'proposed_preserve_val':{'candidate_train_filenames':sorted(tt|vv),'candidate_test_filenames':sorted(vttest),
             'additional_eval_candidates':len(vttest),'counts':{'train':7857-len(tt|vv),'val':164,'test':127-len(vttest),'total':8148-len(tt|vv)-len(vttest)}},
          'earlier_automated_stage':{'high_pairs':len(automated),'train_candidates':len(automatic_train),
             'candidate_train_filenames':sorted(automatic_train),'counts_train_side_only':{'train':7857-len(automatic_train),'val':164,'test':127,'total':8148-len(automatic_train)},
             'interpretation':'Earlier algorithmic triage stage only; superseded by the final audit-priority graph after targeted visual review.'},
          'executed':False,'interpretation':'Planning candidates only. Temporal source adjacency is confirmed; visual legacy candidates do not have confirmed recording/session identity. No automatic leakage adjudication or file move.',
          'identity_note':'recording_id_a/b identify video files; session_a/b are physical sessions and remain unknown. Recording identity must not be counted as independent session identity.',
          'buffer_plus_visual_sensitivity':{}}
        for seconds in [1,2,5,10]:
            bb=set(boundary_budget[str(seconds*15)]['candidate_train_filenames'])
            similarity_plan['buffer_plus_visual_sensitivity'][str(seconds)]={'frame_buffer':seconds*15,'temporal_train_candidates':len(bb),
                  'visual_train_candidates':len(vv),'intersection':len(bb&vv),'union_train_candidates':len(bb|vv),
                  'remaining_train':7857-len(bb|vv),'val_if_train_side_only':164,'test_if_train_side_only':127,'remaining_total_train_side_only':8148-len(bb|vv),
                  'preserve_test_val':164-len(vtval),'preserve_test_test':127,'preserve_test_total':8148-len(bb|vv)-len(vtval),
                  'preserve_val_val':164,'preserve_val_test':127-len(vttest),'preserve_val_total':8148-len(bb|vv)-len(vttest)}
    prov={'created_utc':datetime.now(timezone.utc).isoformat(),'script':str(Path(__file__).resolve()),'script_sha256':digest(Path(__file__)),
          'inventory_sha256':digest(args.inventory),'historical_evidence':evidence,'records':records,'historical_mapping_mismatches':mismatch,
          'summary':{'all_images':len(inv),'complete_current_metadata':sum(bool(x['meta'].get('source_video')) for x in inv),
           'sha_recovered_missing_metadata':sum(r['provenance_confidence']=='confirmed_sha256_historical_manifest' and not invby[n]['meta'].get('source_video') for n,r in records.items()),
           'confirmed_recording_images':sum(bool(r['recording_id']) for r in records.values()),'recording_unknown_images':sum(not r['recording_id'] for r in records.values()),
           'confirmed_recording_count':len(byrecording),'independent_physical_session_count':None,'physical_session_note':'Three identified recording files all dated 2026-10-13; independence between these captures and legacy files is not documented. No true session count is inferred from video count.',
           'same_frame_cross_split_groups':sameframe_cross,'same_frame_units':len(stereo),'temporal':temporal,'cross_split_temporal_runs':run_summary,'boundary_quarantine_planning':boundary_budget},
          'recordings':recording_summary,'similarity_quarantine_planning':similarity_plan,'limitations':['Historical source videos were not decoded or rehashed. Only bounded textual manifests/reports were read.',
          'SHA-confirmed historical mapping verifies current image identity, not accuracy of every historical acquisition field.',
          'True physical sessions, robot trajectory continuity and independent legacy recording identity remain unknown.',
          'Shared laboratory background alone is not classified as leakage.']}
    save(BASE/'data/provenance.json',prov)
    fieldnames=list(next(iter(pairs.values())).keys())
    with (BASE/'data/temporal_pairs.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fieldnames);writer.writeheader();writer.writerows(sorted(pairs.values(),key=lambda p:(p['delta_frames'],p['split_a'],p['split_b'],p['image_a'],p['image_b'])))
    dist={s:describe([x for x in inv if x['split']==s],records) for s in SPLITS}
    illustrative={}
    test=dist['test']
    for label,n in [('all_test_images',test['usable_images']),('positive_images',test['positive_images']),('negative_images',test['negative_images'])]+[(f+'_positive_images',test['scenarios'][f]['positive_images']) for f in FLAGS[:-1]]:
        illustrative[label]={'n':n,'all_correct_wilson95':wilson(n,n),'one_error_wilson95':wilson(max(0,n-1),n),
                             'nearest_integer_80pct_successes':round(.8*n),'nearest_integer_80pct_wilson95':wilson(round(.8*n),n),
                             'unit':'independent Bernoulli trials assumed for illustration only'}
    power={'created_utc':datetime.now(timezone.utc).isoformat(),'split_statistics':dist,'combined':describe(inv,records),
      'illustrative_intervals':illustrative,'actual_model_predictions_available':False,'actual_recall':None,'actual_AP_or_mAP':None,
      'interval_note':'These are hypothetical binomial Wilson intervals, not observed model metrics and not valid confidence intervals for AP. Correlated stereo/adjacent frames make image-level intervals optimistic.',
      'formulas':{'wilson':'(p+z²/(2n) ± z sqrt[p(1-p)/n+z²/(4n²)])/(1+z²/n), z=1.959963984540054',
                  'planning_n':'ceil(z² * 0.25 / margin²), conservative worst-case independent Bernoulli proportion planning',
                  'cluster_design_effect':'n_eff ≈ n/[1+(m-1)rho]; illustrative exchangeable equal-size clusters, neither m nor rho estimated here'},
      'planning_independent_trials':{str(e):n_worst(e) for e in [.10,.075,.05,.03]},
      'negative_zero_fp_upper95_wilson':wilson(0,test['negative_images'])[1],
      'negative_zero_fp_n_for_upper95_1pct_wilson':math.ceil(1.959963984540054**2*(1/.01-1)),
      'recommended_analysis':'Fix detection/confidence/IoU protocol before looking at held-out results. Use paired predictions across models and recording/session or trajectory-cluster bootstrap when enough independent clusters exist. Multiple training seeds describe training variation; they do not create independent test data.',
      'instance_attribute_assignment_available':False,
      'session_counts':{'confirmed_recordings':len(byrecording),'independent_sessions':None,'unknown_recording_usable_images':sum(not records[x['filename']]['recording_id'] for x in inv if x['usable'])}}
    save(BASE/'data/statistical_power.json',power)
    lines=['# 来源、时序与统计复核','',f"当前metadata来源完整6508张；历史manifest与本次图片SHA256核对后，另恢复{prov['summary']['sha_recovered_missing_metadata']}张，来源已确认共{prov['summary']['confirmed_recording_images']}张，{prov['summary']['recording_unknown_images']}张legacy仍不知道视频/场次。",'',
      '完整来源对应3个录像文件；不能据此宣称3个独立采集session。所有录像文件名均指向2026-10-13；18:13及18:15录制可能处于同一次实验，未强行合并或拆分session。', '',
      '同一源帧（含左右目）跨split组数：'+str(len(sameframe_cross))+'。这不意味着相邻帧或录像级独立。','',
      '| 录像 / split对 | 最小帧间隔 | 最小秒数 | <=15帧图像对 | <=150帧图像对 |','|---|---:|---:|---:|---:|']
    for k,v in temporal.items():
        lines.append(f"| {k.replace('|',' / ')} | {v['minimum_delta_frames']} | {v['minimum_delta_seconds']:.4f} | {v['threshold_counts']['15']['image_pairs']} | {v['threshold_counts']['150']['image_pairs']} |")
    lines+=['','阈值1/5/15/30/75/150帧的全部候选计数在provenance.json中；temporal_pairs.csv按双向最近来源时间列出图像对（包含同最小距离下的左右目组合）。连续段以观测采样最大间隔15/75/150帧操作性定义，不能替代运动事件/场景人工确认。', '',
      '| split | 可用 | 有球 | 无球 | 框 | Small 正图/图内总框 | Occluded 正图/图内总框 | Blurred 正图/图内总框 |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for s,d in dist.items():
        lines.append(f"| {s} | {d['usable_images']} | {d['positive_images']} | {d['negative_images']} | {d['boxes']} | "+' | '.join(f"{d['scenarios'][f]['positive_images']}/{d['scenarios'][f]['boxes']}" for f in FLAGS[:-1])+' |')
    lines+=['','场景属于图片级标签。表中场景框数为带该flag的有球图内所有有效足球框；多球图缺少实例级场景属性，不能宣称每个框都属于该专项。当前Test均为单球正图，故专项正图/框分母一致。', '',
      'test的Small14张均有球，来自7个已知立体时刻（帧5119–5164，仅3.0秒）；Occluded26张均有球，来自14个已知时刻（帧4976–5085，仅7.27秒）；Blurred44张中仅30张有球，其中14张来自7个已知立体时刻（跨度18.67秒），其余16张为来源未知legacy正图。单一已知录像和相关双目/邻帧使有效独立样本数更小。', '',
      'Small现行政策：单目图长边归一672时完整球最长边约<=40px；遮挡残留小片不能直接视为小球，详见.agents/skills/football-dataset-curation/references/schema-and-review.md。几何尺寸分档仅描述label，不代替完整球大小人工判断。','',
      '未运行模型，不能给实际Recall、AP或mAP。statistical_power.json中Wilson95%区间完全是假设结果示例（0错、1错或约80%成功）；图像独立假设偏乐观。', '',
      '| Test子集 | n | 假设0错 Wilson95% | 假设1错 Wilson95% |','|---|---:|---|---|']
    for name,d in illustrative.items():
        fmt=lambda z:'['+', '.join(f'{100*v:.1f}%' for v in z)+']' if z else 'N/A'
        lines.append(f"| {name} | {d['n']} | {fmt(d['all_correct_wilson95'])} | {fmt(d['one_error_wilson95'])} |")
    lines+=['','保守独立二项样本规划：95%区间目标半宽±10%约97，±7.5%约171，±5%约385，±3%约1068。各专项分母须分别满足；多标签能共用部分图，但双目或连续帧不能作为独立采集补足。48张无球若假设0误检，Wilson95%上界仍约7.4%；这不是已测到的误检率。', '',
      '科研判断：现有Test适合开发诊断，不能单独支撑可靠的小目标、遮挡或模糊专项论文结论；也不足以证明几个百分点的改进。多个训练种子不增加独立Test数；消融需冻结评测协议、同一独立Test和成对预测，并报告种子波动与按真实场次/轨迹聚类的不确定性。','',
      '来源检查不修改原始图片、label、metadata或split；只写审计输出。']
    (BASE/'data/provenance_summary.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'provenance':prov['summary'],'mapping_mismatches':mismatch,'temporal_rows':len(pairs),'test':test,'outputs':['data/provenance.json','data/temporal_pairs.csv','data/statistical_power.json','data/provenance_summary.md']},ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
