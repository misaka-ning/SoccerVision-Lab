#!/usr/bin/env python3
"""CPU-only review of a recovered E04-0 collection. Never runs inference."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def statistics(values):
    a = np.asarray(values, dtype=np.float64)
    require(a.size > 0 and np.isfinite(a).all(), 'Missing/nonfinite measurement')
    return dict(n=len(a), mean=float(a.mean()), p50=float(np.percentile(a, 50)),
                p95=float(np.percentile(a, 95)), p99=float(np.percentile(a, 99)))


def csv_rows(path):
    with path.open() as stream:
        return [{k: float(v) for k, v in row.items()} for row in csv.DictReader(stream)]


def review(run, collection):
    manifest = read(collection / 'collection_file_manifest.json')
    for item in manifest['files']:
        path = collection / item['path']
        require(collection in path.resolve().parents and path.is_file(), 'Invalid artifact path')
        require(path.stat().st_size == item['bytes'] and digest(path) == item['sha256'], 'Artifact changed: ' + str(path))
    complete = read(collection / 'STAGE0_COLLECTION_COMPLETE.json')
    require(complete['contract_sha256'] == digest(run / 'frozen_contract.json'), 'Contract mismatch')
    require(complete['original_models_unchanged'], 'Model integrity failed')
    before = read(collection / 'protected_models_before.json')
    require(before == read(collection / 'protected_models_after.json'), 'Protected models changed')
    jobs = read(collection / 'stage0_jobs.json')
    require({x['name'] for x in jobs} == {'golden', 'engine_system', 'detector_r1', 'detector_r2', 'detector_r3'}, 'Unexpected jobs')
    require(all(x['status'] == 'complete' and x['returncode'] == 0 for x in jobs), 'Incomplete attempt requires manual review')

    golden_dir = collection / 'stage0_golden_attempt1'
    golden = read(golden_dir / 'golden.json')
    cases = read(run / 'val_cases/cases.json')
    require(golden['split'] == 'val' and not golden['test_accessed'], 'Not approved Val')
    require([x['pair_key'] for x in golden['records']] == [x['pair_key'] for x in cases['pairs']], 'Golden pair order changed')
    require(golden['pairs'] == len(golden['records']) == 61, 'Golden missing cases')
    runtime = read(golden_dir / 'effective_runtime.json')
    require(runtime['warmup_excluded'] == 100 and runtime['top_k'] == 5, 'Warmup/top-k mismatch')
    require(runtime['nms']['name'] == 'nms_fallback', 'NMS changed')
    args = runtime['effective_predictor_args']
    require(all(args[k] == v for k, v in dict(conf=0.45, iou=0.7, classes=[0], max_det=300, agnostic_nms=False).items()), 'Effective args changed')
    payload_fields = {'type', 'timestamp', 'valid', 'confidence', 'x_m', 'y_m', 'z_m'}
    for index, record in enumerate(golden['records']):
        require(record['frame_idx'] == index, 'Frame index mismatch')
        payload = record['ros_payload']
        require(set(payload) == payload_fields and payload['timestamp'] == record['replay_timestamp'], 'Protocol/timestamp mismatch')
        require(payload['type'] == 'ball_position_camera', 'Payload type changed')
        if payload['valid']:
            require(np.isfinite([payload[k] for k in ['x_m', 'y_m', 'z_m', 'confidence']]).all(), 'Invalid 3D output')
        for group in record['candidates']:
            require(len(group) <= 5 and all(x['class_id'] == 0 and x['score'] >= 0.45 for x in group), 'Candidate semantics changed')
            require([x['score'] for x in group] == sorted([x['score'] for x in group], reverse=True), 'Candidate order changed')
        with np.load(golden_dir / (record['pair_key'] + '.npz'), allow_pickle=False) as arrays:
            for key, shape in [('input', (2, 3, 640, 640)), ('raw', (2, 5, 8400))]:
                a = arrays[key]
                require(a.shape == shape and a.dtype == np.float32 and np.isfinite(a).all(), 'Invalid frozen tensor: ' + key)
            require(arrays['input'].min() >= 0 and arrays['input'].max() <= 1, 'Input normalization mismatch')
            for key in ['left_final_boxes', 'right_final_boxes']:
                a = arrays[key]
                require(a.ndim == 2 and a.shape[1] == 6 and a.dtype == np.float32 and np.isfinite(a).all(), 'Invalid final boxes')

    bench = next(collection.glob('stage0_engine_system_attempt1/*/summary.json')).parent
    summary = read(bench / 'summary.json')
    require(summary['status'] == 'complete' and len(summary['rounds']) == 6, 'Benchmark incomplete')
    output, round_stats = {}, []
    for mode in ['engine', 'system']:
        paths = sorted(bench.glob('*_' + mode))
        require(len(paths) == 3, 'Expected three rounds: ' + mode)
        all_rows = []
        elapsed = publish_elapsed = 0.0
        publish_intervals = 0
        for path in paths:
            progress = read(path / 'progress.json')
            rows = csv_rows(path / 'frames.csv')
            require(progress['stage'] == '完成' and progress['warmup_total'] == 100 and progress['elapsed'] >= 60, 'Round length/warmup failed')
            require(len(rows) == progress['completed'] and len(rows) > 100, 'Raw sample count mismatch')
            all_rows.extend(rows)
            key = 'engine_ms' if mode == 'engine' else 'read_ready_to_publish_ms'
            item = dict(mode=mode, round=path.name, **statistics([x[key] for x in rows]))
            if mode == 'system':
                seconds = rows[-1]['cycle_end'] - rows[0]['cycle_start']
                item['processing_hz'] = len(rows) / seconds
                elapsed += seconds
                publish_elapsed += rows[-1]['publish_end'] - rows[0]['publish_end']
                publish_intervals += len(rows) - 1
            round_stats.append(item)
        output[mode] = {key: statistics([x[key] for x in all_rows]) for key in all_rows[0] if key.endswith('_ms')}
        if mode == 'system':
            output[mode].update(processing_hz=len(all_rows) / elapsed, publish_hz=publish_intervals / publish_elapsed)
        means = [x['mean'] for x in round_stats if x['mode'] == mode]
        output[mode]['round_mean_cv_percent'] = float(np.std(means) / np.mean(means) * 100)
    detector_rows = []
    for path in sorted(collection.glob('stage0_detector_r*_attempt1')):
        runtime = read(path / 'effective_runtime.json')
        result = read(path / 'result.json')
        rows = csv_rows(path / 'frames.csv')
        require(runtime['warmup_excluded'] == 100 and result['seconds'] == 60 and len(rows) == result['samples'], 'Replay length/warmup mismatch')
        detector_rows.extend(rows)
        round_stats.append(dict(mode='detector', round=path.name, **statistics([x['detector_wall_ms'] for x in rows])))
    require(sum(x['mode'] == 'detector' for x in round_stats) == 3, 'Missing replay round')
    output['fixed_detector'] = {key: statistics([x[key] for x in detector_rows]) for key in detector_rows[0] if key.endswith('_ms')}
    means = [x['mean'] for x in round_stats if x['mode'] == 'detector']
    output['fixed_detector']['round_mean_cv_percent'] = float(np.std(means) / np.mean(means) * 100)
    telemetry = [json.loads(line) for line in (collection / 'telemetry_stage0.jsonl').read_text().splitlines()]
    return dict(status='data_checks_passed', contract_sha256=complete['contract_sha256'], manifest_files_verified=len(manifest['files']),
                protected_models=len(before), golden_pairs=len(golden['records']),
                golden_coverage=dict(empty_eyes=sum(not c for r in golden['records'] for c in r['candidates']),
                    asymmetric_pairs=sum(bool(r['candidates'][0]) != bool(r['candidates'][1]) for r in golden['records']),
                    valid_3d_measurements=sum(r['measurement']['valid'] for r in golden['records']),
                    max_candidates_per_eye=max(len(c) for r in golden['records'] for c in r['candidates'])),
                metrics=output, rounds=round_stats,
                telemetry=dict(samples=len(telemetry), gpu_frequencies_hz=sorted({int(t['gpu_hz']) for t in telemetry}),
                    gpu_temperature_c=[min(int(t['thermal']['GPU-therm']) for t in telemetry) / 1000,
                                       max(int(t['thermal']['GPU-therm']) for t in telemetry) / 1000]),
                limits=['Golden is a frozen reference, not an optimized candidate correctness pass or physical 3D truth.',
                        'System scene differs from fixed replay; Viser differs from E03. No speedup attribution.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--collection-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = review(args.run_dir.resolve(), args.collection_dir.resolve())
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    print(json.dumps({k: result[k] for k in ['status', 'manifest_files_verified', 'protected_models', 'golden_pairs', 'golden_coverage']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
