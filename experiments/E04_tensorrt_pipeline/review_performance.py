#!/usr/bin/env python3
"""Independently recompute a recovered E04 performance matrix on CPU."""
import argparse
import csv
import datetime
import hashlib
import json
from pathlib import Path
import statistics

from performance_plan import schedule, stats, summarize
from run_performance_robot import validate_hooks


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def midpoint(job):
    def stamp(text):
        return datetime.datetime.fromisoformat(text).timestamp()
    return (stamp(job['started_utc']) + stamp(job['completed_utc'])) / 2


def paired_change(before, after, candidate, metric):
    a, b, c = [j['metrics'][metric]['mean'] for j in (before, after, candidate)]
    baseline = (a + b) / 2
    weight = (midpoint(candidate) - midpoint(before)) / (midpoint(after) - midpoint(before))
    interpolated = a + (b - a) * weight
    return dict(round=candidate['round'], candidate_ms=c, baseline_ms=baseline,
                saved_ms=baseline - c, reduction_percent=(baseline - c) / baseline * 100,
                interpolated_baseline_ms=interpolated,
                interpolated_reduction_percent=(interpolated - c) / interpolated * 100)


def review(root):
    jobs = read(root / 'performance_jobs.json')
    payload = read(root / 'performance_manifest.json')
    fingerprint = digest(root / 'performance_manifest.json')
    errors, rows_by_job, reviewed = [], {}, []
    expected = schedule(['execution', 'detector', 'diagnostic'])
    if [j['name'] for j in jobs] != [j['name'] for j in expected]:
        errors.append('Unexpected/missing/duplicate schedule jobs')
    integrity = read(root / 'offline_recovery_v1_integrity.json')
    if integrity['errors'] or integrity['performance_manifest_sha256'] != fingerprint:
        errors.append('Recapture integrity failed')
    for job in jobs:
        try:
            assert job['status'] == 'complete' and job['returncode'] == 0
            assert job['payload_sha256'] == fingerprint
            assert job['warmup'] == 100 and job['seconds'] == 60
            for item in job['artifacts']:
                path = root / item['path']
                assert path.stat().st_size == item['bytes'] and digest(path) == item['sha256']
            output = root / Path(job['output']).name
            metrics = summarize(output / 'frames.csv', job['scope'])
            with (output / 'frames.csv').open() as stream:
                rows = [{k: float(v) for k, v in r.items()} for r in csv.DictReader(stream)]
            rows_by_job[job['name']] = rows
            assert len(rows) == job['samples']
            for key, value in metrics.items():
                for field in ('mean', 'p50', 'p95', 'p99', 'min', 'max', 'n'):
                    assert abs(value[field] - job['metrics'][key][field]) < 1e-9
            result = read(output / 'result.json')
            if job['scope'] == 'execution':
                assert result['restore'] == 'complete'
                assert result['first_warmup_matches_golden'] and result['final_output_matches_golden']
                assert result['formal_100_warmup_60_seconds'] and result['measured_loop_seconds'] >= 60
                assert result['samples'] == len(rows)
                if job['variant'] == 'graph':
                    state = result['before_restore']
                    assert state['capture_count'] == 1 and state['fallback_count'] == 0
                    assert state['replay_count'] == state['input_update_count'] == 100 + len(rows)
            else:
                hook = validate_hooks(root / (output.name + '_hooks.json'), job, len(rows), payload['expected_runtime'])
                runtime = read(output / 'effective_runtime.json')
                assert runtime['warmup_excluded'] == 100 and result['seconds'] == 60
                assert result['samples'] == len(rows)
                # This fixed pair has exactly one final candidate in each eye.
                assert all(r['left_candidates'] == 1 and r['right_candidates'] == 1 for r in rows)
                if 'a2' in job['switches'].get('postprocess', ''):
                    end = hook['detectors'][0]['before_restore']['components']['postprocess']
                    warm = hook['warmup_checkpoint'][0]['components']['postprocess']
                    for key in ('packed_batches', 'd2h_calls'):
                        assert end[key] - warm[key] == len(rows)
                    assert end['packed_rows'] - warm['packed_rows'] == 2 * len(rows)
                if job['variant'] == 'C1_probe':
                    for key, value in hook['measurement_only_c1_timings'].items():
                        assert abs(value['mean_ms'] - metrics['c1_' + key + '_method_ms']['mean']) < 1e-7
            reviewed.append(dict(name=job['name'], variant=job['variant'], scope=job['scope'],
                                 samples=len(rows), metrics=metrics))
        except Exception as error:
            errors.append(dict(job=job['name'], error=repr(error)))
    by_name = {j['name']: j for j in jobs}
    summaries = {}
    for variant in ['R0', 'A1', 'A2', 'A1_A2', 'B_Graph', 'C2']:
        selected = [j for j in jobs if j['scope'] == 'detector' and j['variant'] == variant]
        rows = [r for j in selected for r in rows_by_job.get(j['name'], [])]
        metrics = {key: stats([r[key] for r in rows]) for key in rows[0] if key.endswith('_ms')}
        paired = []
        for job in selected:
            if variant != 'R0':
                before = by_name['detector_r%d_00_R0' % job['round']]
                after = by_name['detector_r%d_06_R0' % job['round']]
                paired.append(paired_change(before, after, job, 'detector_wall_ms'))
        summaries[variant] = dict(jobs=len(selected), pooled_metrics=metrics, paired_rounds=paired,
                                 round_means=[j['metrics']['detector_wall_ms']['mean'] for j in selected])
        if paired:
            summaries[variant]['mean_round_reduction_percent'] = statistics.mean(p['reduction_percent'] for p in paired)
    execution = {}
    for variant in ['b0', 'graph']:
        selected = [j for j in jobs if j['scope'] == 'execution' and j['variant'] == variant]
        rows = [r for j in selected for r in rows_by_job[j['name']]]
        execution[variant] = {key: stats([r[key] for r in rows]) for key in rows[0] if key.endswith('_ms')}
    pairs = []
    for index in range(1, 4):
        a, b = [by_name['execution_r%d_%s' % (index, v)] for v in ('b0', 'graph')]
        av, bv = [j['metrics']['execution_cuda_ms']['mean'] for j in (a, b)]
        pairs.append(dict(round=index, baseline_ms=av, graph_ms=bv, saved_ms=av-bv, reduction_percent=(av-bv)/av*100))
    telemetry = [json.loads(line) for line in (root / 'telemetry_stage0.jsonl').read_text().splitlines()]
    frequencies = {}
    temps = []
    for entry in telemetry:
        freq = entry.get('gpu_hz', 'unavailable')
        frequencies[freq] = frequencies.get(freq, 0) + 1
        if 'GPU-therm' in entry.get('thermal', {}):
            temps.append(float(entry['thermal']['GPU-therm']) / 1000)
    drifts = [by_name['detector_r%d_06_R0' % i]['bracket_baseline_drift_percent'] for i in range(1, 4)]
    if any(v > 3 for v in drifts):
        errors.append('R0 bracket drift exceeded 3%')
    return dict(status='passed_for_system_single_component_benchmark' if not errors else 'failed_requires_review',
                errors=errors, performance_manifest_sha256=fingerprint, jobs=len(jobs),
                all_samples=sum(j['samples'] for j in jobs), job_reviews=reviewed,
                detector=summaries, execution=execution, execution_pairs=pairs,
                c1_segments=next(j['c1_segments'] for j in jobs if j['scope'] == 'diagnostic'),
                baseline_bracket_drift_percent=drifts,
                telemetry=dict(samples=len(telemetry), gpu_frequency_hz_histogram=frequencies,
                               gpu_temp_c_range=[min(temps), max(temps)]),
                system_tested=False, production_adopted=False, combinations_tested=False,
                statistics_note='Pooled quantiles are over raw frames. Paired gains use equally weighted three round R0 bracket means; time interpolation is sensitivity only. Frames are not independent experiment repeats.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recovered', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    value = review(args.recovered)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k: value[k] for k in ['status', 'jobs', 'all_samples', 'errors', 'baseline_bracket_drift_percent', 'telemetry']}, indent=2))
    raise SystemExit(bool(value['errors']))
