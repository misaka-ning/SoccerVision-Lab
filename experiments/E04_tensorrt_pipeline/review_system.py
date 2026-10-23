#!/usr/bin/env python3
"""Review original E04 single-component live-system CSVs without GPU work."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics

from performance_plan import schedule, stats, summarize
from review_performance import midpoint, paired_change
from run_performance_robot import validate_hooks


def read(path):
    return json.loads(path.read_text())


def review(root, scene_label):
    jobs = read(root / 'performance_jobs.json')
    fingerprint = hashlib.sha256((root / 'performance_manifest.json').read_bytes()).hexdigest()
    payload = read(root / 'performance_manifest.json')
    selected = [j for j in jobs if j['scope'] == 'system']
    errors, reviewed, rows_by_name = [], [], {}
    if [j['name'] for j in selected] != [s['name'] for s in schedule(['system'])]:
        raise ValueError('Unexpected/missing/duplicate system schedule')
    for job in jobs:
        for item in job.get('artifacts', []):
            path = root / item['path']
            if not path.is_file() or path.stat().st_size != item['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                errors.append(dict(job=job['name'], artifact=item['path']))
    for job in selected:
        try:
            assert job['status'] == 'complete' and job['returncode'] == 0
            assert job['warmup'] == 100 and job['seconds'] == 60
            assert job['payload_sha256'] == fingerprint
            output = root / Path(job['output']).name
            metrics = summarize(output / 'frames.csv', 'system')
            with (output / 'frames.csv').open() as stream:
                rows = [{k: float(v) for k, v in row.items()} for row in csv.DictReader(stream)]
            rows_by_name[job['name']] = rows
            assert len(rows) == job['samples']
            for key, value in metrics.items():
                if key.endswith('_ms'):
                    for field in ['n', 'mean', 'p50', 'p95', 'p99', 'min', 'max']:
                        assert abs(value[field] - job['metrics'][key][field]) < 1e-9
                elif key in ['processing_hz', 'publish_hz', 'hz_sample_seconds', 'publish_sample_seconds']:
                    assert abs(value - job['metrics'][key]) < 1e-9
            hook = validate_hooks(root / (output.name + '_hooks.json'), job, len(rows), payload['expected_runtime'])
            progress = read(output / 'progress.json')
            assert progress['warmup_total'] == 100 and progress['elapsed'] >= 60 and progress['completed'] == len(rows)
            assert read(output / 'result.json')['status'] == 'complete'
            config = read(output / 'deployment_config.json')
            assert config['ros_domain_id'] == '87' and config['input_shape'] == [2, 3, 640, 640]
            item = dict(name=job['name'], variant=job['variant'], round=job['round'], metrics=metrics,
                        samples=len(rows), left_nonempty=sum(r['left_candidates'] > 0 for r in rows),
                        right_nonempty=sum(r['right_candidates'] > 0 for r in rows),
                        stereo_nonempty=sum(r['left_candidates'] > 0 and r['right_candidates'] > 0 for r in rows))
            if 'a2' in job['switches'].get('postprocess', ''):
                end = hook['detectors'][0]['before_restore']['components']['postprocess']
                warm = hook['warmup_checkpoint'][0]['components']['postprocess']
                delta = {key: end[key] - warm[key] for key in ['predict_calls', 'packed_batches', 'packed_rows', 'd2h_calls', 'd2h_bytes', 'pack_wall_ms_total']}
                assert delta['predict_calls'] == len(rows)
                assert delta['packed_batches'] == delta['d2h_calls'] == sum(r['left_candidates'] + r['right_candidates'] > 0 for r in rows)
                assert delta['packed_rows'] >= sum(r['left_candidates'] + r['right_candidates'] for r in rows)
                assert delta['d2h_bytes'] == 24 * delta['packed_rows']
                assert abs(delta['pack_wall_ms_total'] - sum(r['a2_pack_method_ms'] for r in rows)) < 1e-6
                item['a2_measurement_counts'] = delta
            reviewed.append(item)
        except Exception as error:
            errors.append(dict(job=job['name'], error=repr(error)))
    by_name = {j['name']: j for j in selected}
    variants = {}
    for variant in ['R0', 'A1', 'A2', 'A1_A2', 'B_Graph', 'C2']:
        group = [j for j in selected if j['variant'] == variant]
        rows = [r for j in group for r in rows_by_name[j['name']]]
        pooled = {k: stats([r[k] for r in rows]) for k in rows[0] if k.endswith('_ms')}
        sample_seconds = sum(j['metrics']['hz_sample_seconds'] for j in group)
        publish_seconds = sum(j['metrics']['publish_sample_seconds'] for j in group)
        per_round = []
        if variant != 'R0':
            for job in group:
                before = by_name['system_r%d_00_R0' % job['round']]
                after = by_name['system_r%d_06_R0' % job['round']]
                entry = dict(round=job['round'], latency={})
                for metric in ['detector_ms', 'cycle_ms', 'read_ready_to_publish_ms']:
                    entry['latency'][metric] = paired_change(before, after, job, metric)
                    baseline_rows = rows_by_name[before['name']] + rows_by_name[after['name']]
                    baseline_stats = stats([r[metric] for r in baseline_rows])
                    entry['latency'][metric]['baseline_pooled_p95'] = baseline_stats['p95']
                    entry['latency'][metric]['baseline_pooled_p99'] = baseline_stats['p99']
                    entry['latency'][metric]['candidate_p95'] = job['metrics'][metric]['p95']
                    entry['latency'][metric]['candidate_p99'] = job['metrics'][metric]['p99']
                for metric in ['processing_hz', 'publish_hz']:
                    baseline = (before['metrics'][metric] + after['metrics'][metric]) / 2
                    value = job['metrics'][metric]
                    entry[metric] = dict(baseline=baseline, candidate=value, gain_percent=(value/baseline-1)*100)
                per_round.append(entry)
        variants[variant] = dict(samples=len(rows), pooled_metrics=pooled,
            processing_hz=len(rows)/sample_seconds,
            publish_hz=sum(j['samples']-1 for j in group)/publish_seconds,
            round_processing_hz=[j['metrics']['processing_hz'] for j in group], paired_rounds=per_round,
            left_nonempty=sum(r['left_candidates']>0 for r in rows),
            right_nonempty=sum(r['right_candidates']>0 for r in rows),
            stereo_nonempty=sum(r['left_candidates']>0 and r['right_candidates']>0 for r in rows))
        if per_round:
            variants[variant]['mean_round_processing_hz_gain_percent'] = statistics.mean(r['processing_hz']['gain_percent'] for r in per_round)
    drift = [by_name['system_r%d_06_R0' % i]['bracket_baseline_drift_percent'] for i in range(1,4)]
    if max(drift)>3: errors.append('R0 baseline drift exceeded 3%')
    count = sum(j['samples'] for j in selected)
    stereo = sum(x['stereo_nonempty'] for x in reviewed)
    return dict(status='passed_empty_scene_only' if not errors and scene_label=='empty' else 'reviewed_pending_scene_validation' if not errors else 'failed_requires_review',
                errors=errors, scene_label=scene_label, scene_source='user_confirmed_empty_scene' if scene_label=='empty' else 'target_scene',
                jobs=len(selected), samples=count, job_reviews=reviewed, variants=variants,
                performance_manifest_sha256=fingerprint, baseline_drift_percent=drift,
                stereo_nonempty_frames=stereo, stereo_nonempty_fraction=stereo/count,
                measurement_validity_recorded=all('measurement_valid' in r for rows in rows_by_name.values() for r in rows),
                valid_for_target_scene_acceptance=False, production_adopted=False, combinations_approved=False,
                note='Hz aggregates sum per-job observed durations; no cross-process timestamp gaps. Quantiles pool raw frames; paired gains average independent rounds. Empty scene cannot validate detected-box return or stereo localization performance.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recovered',type=Path,required=True)
    parser.add_argument('--scene-label',choices=['empty','target'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=review(args.recovered,args.scene_label)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ['status','errors','jobs','samples','stereo_nonempty_frames','measurement_validity_recorded','baseline_drift_percent']},indent=2))
    raise SystemExit(bool(result['errors']))
