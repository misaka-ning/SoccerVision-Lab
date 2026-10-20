#!/usr/bin/env python3
"""Validate and seal audit outputs. Never writes to the canonical dataset."""
import ast
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=Path('/home/misaka/workspace/datasets')
os.environ['OMP_NUM_THREADS']='1'
try: os.nice(10)
except OSError: pass

def load(p): return json.loads(p.read_text(encoding='utf-8'))
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()
def save(p,v): p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def main():
    started=load(ROOT/'data/start-state.json')
    inventory=load(ROOT/'data/inventory.json')
    summary=load(ROOT/'data/inventory-summary.json')
    similarity=load(ROOT/'data/similarity-summary.json')
    triage=load(ROOT/'data/final-triage-summary.json')
    embedding=load(ROOT/'data/embedding-model.json')
    provenance=load(ROOT/'data/provenance.json')
    isolation=load(ROOT/'isolation/verification.json')
    pairs=rows(ROOT/'cross_split_duplicates.csv')
    issues=rows(ROOT/'annotation_issues.csv')
    excluded=rows(ROOT/'excluded_samples_audit.csv')
    checks={}
    def check(k,v):
        checks[k]=bool(v)
        if not v: raise AssertionError(k)
    for kind in ('metadata','yaml'):
        src=started['source'][kind]
        check(kind+'_source_unchanged',digest(Path(src['path']))==src['sha256'])
    check('inventory8398_usable8148',len(inventory)==8398 and sum(r['usable'] for r in inventory)==8148)
    check('isolation_independent_PASS',isolation['status']=='PASS' and isolation['success'])
    check('pairs22391_high74',len(pairs)==22391 and sum(r['risk_level']=='high' for r in pairs)==74)
    check('pairs_user_reviews_blank',all(r['review_status']=='' for r in pairs))
    check('actual_visual_seen50',sum(r['assistant_visual_reviewed']=='True' for r in pairs)==50)
    refined_count=sum(r['ssim_resolution']=='256x144' for r in pairs)
    check('ssim_refined61',refined_count==61)
    check('annotation310_user_reviews_blank',len(issues)==310 and all(r['review_result']=='' for r in issues))
    check('excluded250',len(excluded)==250)
    check('exact_duplicates0',not summary['file_sha_duplicate_index_groups'] and not summary['pixel_sha_duplicate_index_groups'])
    required=['AUDIT_REPORT.md','cross_split_duplicates.csv','split_distribution.csv','annotation_issues.csv',
              'excluded_samples_audit.csv','leakage_review.html','proposed_split_plan.md','audit_manifest.json']
    for n in required[:-1]: check('required_'+n,(ROOT/n).is_file())
    scripts=[]
    for p in sorted((ROOT/'scripts').glob('*.py')):
        ast.parse(p.read_text(encoding='utf-8'),filename=str(p))
        scripts.append(dict(path=str(p.relative_to(ROOT)),sha256=digest(p),bytes=p.stat().st_size))
    check('python_scripts_syntax',True)
    active={}; archived={}
    for split in ('train','val','test'):
        active[split]={kind:len(list((DATA/kind/split).glob('*'))) for kind in ('images','labels')}
        archived[split]={kind:len(list((DATA/'excluded'/kind/split).glob('*'))) for kind in ('images','labels')}
    check('active_split_counts',active=={s:{k:n for k in ('images','labels')} for s,n in [('train',7857),('val',164),('test',127)]})
    check('archive_split_counts',archived=={s:{k:n for k in ('images','labels')} for s,n in [('train',243),('val',6),('test',1)]})
    check('no_source_cache',not list(DATA.rglob('*.cache')))
    for name in ('final-independent-review.json','final-path-validation.json','html-ui-validation.json'):
        check('validation_log_'+name,(ROOT/'logs'/name).is_file())
    check('independent_final_PASS',load(ROOT/'logs/final-independent-review.json')['status']=='PASS')
    path_result=load(ROOT/'logs/final-path-validation.json')
    check('path_validation_PASS',path_result.get('status')=='PASS')
    check('reproduction_notes',(ROOT/'REPRODUCE.md').is_file() and (ROOT/'data/provenance-evidence/sources.json').is_file())
    checked_at=datetime.now(timezone.utc).isoformat()
    save(ROOT/'logs/final-validation.json',dict(status='PASS',performed_at_utc=checked_at,checks=checks,
         scope='Audit artifacts and final source metadata/YAML/path counts. Full16796 source byte identity is independently recorded in isolation/verification.json.',
         figures_visually_opened=['figures/split-and-test-counts.png','figures/illustrative-wilson.png','figures/similarity-signals.png'],
         source_images_or_labels_changed_by_this_script=False))
    versions={}
    for package in ('numpy','Pillow','opencv-python','torch','torchvision','ultralytics','matplotlib','pandas'):
        try: versions[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError: versions[package]=None
    file_index=[]
    excluded_index={'audit_manifest.json','data/output-files.json'}
    for p in sorted(ROOT.rglob('*')):
        relative=str(p.relative_to(ROOT))
        if relative in excluded_index or not (p.is_file() or p.is_symlink()): continue
        if p.is_symlink():
            file_index.append(dict(path=relative,type='symlink',target=os.readlink(p),target_exists=p.exists(),
                                   content_sha256=None,note='Discovery view reference only; link target bytes are source data, not an output copy.'))
        else:
            file_index.append(dict(path=relative,type='regular_file',bytes=p.stat().st_size,sha256=digest(p)))
    save(ROOT/'data/output-files.json',dict(generated_utc=checked_at,entries=file_index,
         self_reference_policy='audit_manifest.json and this index excluded from their own digest list to avoid recursion. Manifest authenticates the index; all other regular outputs have content SHA256. Symlink targets are not traversed.'))
    manifest=dict(schema_version='1.0',audit_id=ROOT.name,conclusion='BLOCKED',audit_execution_complete=True,
        created_at_utc=started['created_at_utc'],completed_at_utc=checked_at,timezone_for_display='Asia/Hong_Kong UTC+08:00',
        output_directory=str(ROOT),canonical_dataset=str(DATA),source_version=started['source'],
        source_snapshot=dict(metadata='data/source-metadata.csv',yaml='data/source-dataset.yaml',
            inventory='data/inventory.json',inventory_sha256=digest(ROOT/'data/inventory.json'),
            current_paths='isolation/verification.json:mapped_file_records',
            image_sha_manifest='data/image-sha256.tsv',label_sha_manifest='data/label-sha256.tsv',pixel_sha_manifest='data/pixel-sha256.tsv'),
        file_counts=dict(metadata_rows=8398,decoded_images=8398,baseline_images=8398,baseline_labels=8398,
            usable_images=8148,excluded_images=250,usable_football_boxes=5417,usable_positive_images=5220,usable_negative_images=2928,
            active_after_isolation=active,archived_after_isolation=archived,original_image_and_label_bytes_checked=16796),
        user_authorized_change=dict(request='可以帮我把那250张图片和label放到和images、labels同级的另外的文件夹中，隔离开来',
            destination=str(DATA/'excluded'),images_moved=250,labels_moved=250,usable_files_moved=0,
            image_and_label_bytes_unchanged=True,metadata_unchanged=True,yaml_unchanged=True,split_fields_unchanged=True,
            manifest=str(DATA/'excluded/manifest.json'),backup='isolation/backup',independent_verification='isolation/verification.json',
            warning='Root metadata intentionally remains the complete8398-row historical ledger.250 excluded paths resolve via the isolation manifest. Do not rerun the move.'),
        environment=dict(python=sys.version,python_executable=sys.executable,platform=platform.platform(),packages=versions,
            compute='CPU; one numerical/OpenCV/Torch thread per process, nice10; no production environment installation',
            thread_environment=dict(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')),
        script_version=dict(strategy='SHA256 of exact saved implementation, not a fabricated Git release',scripts=scripts),
        hashing=dict(file='SHA256(raw bytes)',pixel=summary['pixel_sha256_definition'],phash=summary['phash_definition'],dhash=summary['dhash_definition']),
        thresholds=dict(inventory=summary['thresholds'],hash_hamming_report=[0,2,4,6,8,10,12,16],
            hash_index='BK tree exact64-bit Hamming radius16; candidate pHash<=12 OR dHash<=10',
            cosine_report=[0.90,0.95,0.97,0.98,0.99,0.995],
            candidate_retrieval='Cross split eval-query top5 plus reverse top1, normalized exact blocked dot product; no within-train all-pairs',
            ssim='Gaussian11 sigma1.5, data_range255, valid5px border; base128x72;61 initially high refined256x144,58 remained automated high after refinement',
            ssim_pair_counts=dict(base128x72=22391,refined256x144=refined_count,automated_high_after_refinement=58),
            alignment='Translation diagnostic on58 automated high after refinement; response>=0.3, norm shift<=8px, extra10px border crop;26 valid aligned pairs',
            risk_policy=similarity['risk_policy'],temporal_report_frames=[1,5,15,30,75,150],high_temporal_seconds=1,
            review_thresholds_are_groundtruth=False),
        embedding_model=embedding,random_seed=20261019,
        sampling=dict(stratified_unique_images=64,actual_visual_sample_pages=32,purposeful_legacy_visual_pairs=42,
                      temporal_pair_representatives=8,pair_review_initially_blank=True,annotation_review_initially_blank=True),
        final_candidates=triage,
        source_associations=dict(confirmed_recording_images=7684,recovered_from_sha_matched_manifest=1176,
            confirmed_recording_files=3,legacy_recording_unknown=714,true_independent_physical_session_count=None,
            same_frame_cross_split_known_source_groups=0,confirmed_le_1s_cross_split_image_pairs=32,
            distinct_temporal_pairs=8,temporal_pairs_are_not_independent_events=True,historical_text_evidence='data/provenance-evidence/sources.json'),
        completed_steps=[
            dict(step='A',coverage='All8398 image bytes, full RGB decode, labels, metadata, paths, YAML, class mapping, excluded filtering before/after.'),
            dict(step='B1',coverage='All8398 raw-file and decoded-RGB SHA256; zero exact cross-split groups.'),
            dict(step='B2',coverage='All8398 pHash/dHash indexed cross-split retrieval; threshold sensitivity and independent brute-force checks.'),
            dict(step='B3',coverage='All8148 usable MobileNetV3-small ImageNet1K embeddings; L2 normalization; exact blocked cross-split cosine retrieval/distributions.'),
            dict(step='B4',coverage='22391 candidate SSIM128x72;61 initial high refined256x144,58 remained automated high;26 valid limited alignment diagnostics on those58.'),
            dict(step='B5/C',coverage='7684 source identities from current fields or SHA-confirmed historical manifests; frames, stereo, temporal gaps; unknown identities explicitly preserved.'),
            dict(step='B6/E3',coverage='Offline HTML all22391 candidate pairs;74 evidence comparison pages;42 actual legacy visual pair inspections,8 actual temporal representative inspections,64 actual stratified image inspections.'),
            dict(step='D',coverage='All splits, multi-label joints, positives/negatives/box bins/video groups; Test correlation and conditional illustrative Wilson/planning calculations.'),
            dict(step='E1/E2',coverage='All label geometry/count/NoBall checks; Small/edge candidate screening; subjective scenes only sampled visual observations.'),
            dict(step='F',coverage='Actual installed Ultralytics get_img_files before/after; copies-only4 invalid-label verifier tests; source/cache/model nc mapping inspection; no model instantiation/training.'),
            dict(step='authorized isolation',coverage='250 images+250 labels moved, backup/journal; independent all16796 file SHA and500 archive/backup byte comparisons passed.'),
            dict(step='final validation',coverage='Independent report arithmetic/CSV review, paths, runtime browser pagination/filter checks, figures, source SHA and output index.')],
        not_executed_or_unverifiable=[
            dict(item='DINOv2/FAISS',reason='Not installed; actual pretrained alternative and exact bounded retrieval used instead; no dependency installation.'),
            dict(item='Independent physical sessions and714 legacy original videos/frames',reason='Insufficient reliable acquisition evidence. Recording count is not session count.'),
            dict(item='Full manual8398 reannotation/all22391 candidate adjudication',reason='Audit uses recorded stratified/purposeful visual coverage; assistant observations are not user approval.'),
            dict(item='Universal rotation/perspective/exposure matching or formal no-leak proof',reason='Finite retrieval/diagnostic coverage cannot establish absence of all leakage.'),
            dict(item='Actual Recall/AP/mAP, E00/E01, ablation, multiseed training, production TensorRT update',reason='Not authorized by this audit and expressly prohibited; statistical intervals are hypothetical only.'),
            dict(item='Other cleaning or repartition',reason='Proposals only. Only the later explicitly authorized250-sample isolation was applied.'),
            dict(item='YOLO26s runtime/weight compatibility',reason='Data I/O and installed trainer nc source checked; no model instantiated. E00 COCO32-to-class0 protocol remains to define.')],
        reproduction_notes='REPRODUCE.md',validation=dict(final='logs/final-validation.json',independent='logs/final-independent-review.json',paths='logs/final-path-validation.json',browser='logs/html-ui-validation.json'),
        outputs=dict(required=[dict(path=n,sha256=digest(ROOT/n) if n!='audit_manifest.json' else None) for n in required],
            full_inventory='data/output-files.json',full_inventory_sha256=digest(ROOT/'data/output-files.json'),
            indexed_entries=len(file_index),counts=dict(Counter(r['type'] for r in file_index)),
            self_hash_policy='The manifest has no self digest. File index deliberately excludes itself and the manifest. All other output regular files are hashed.'))
    save(ROOT/'audit_manifest.json',manifest)
    print(json.dumps(dict(status='PASS',conclusion='BLOCKED',manifest=str(ROOT/'audit_manifest.json'),
                         output_entries=len(file_index),checks=len(checks)),ensure_ascii=False))

if __name__=='__main__': main()
