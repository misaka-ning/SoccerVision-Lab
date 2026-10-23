#!/usr/bin/env python3
"""CPU-only coordinator review of full R0/R4/R5 Golden equivalence."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from compare_goldens import compare


def read(path):
    return json.loads(path.read_text())


def review(run, phase):
    recovered = phase / 'recovered_v1'
    reference = run / 'collection_v1/stage0_golden_attempt1'
    manifest = read(recovered / 'phase_manifest.json')
    fingerprint = hashlib.sha256((recovered / 'phase_manifest.json').read_bytes()).hexdigest()
    integrity = read(recovered / 'correctness_recovery_v1_integrity.json')
    if integrity['errors'] or integrity['phase_manifest_sha256'] != fingerprint:
        raise ValueError('Integrity evidence failed')
    jobs = read(recovered / 'jobs.json')
    if [j['name'] for j in jobs] != ['R0', 'R4_AB', 'R5_ABC']:
        raise ValueError('Unexpected/missing/duplicate correctness schedule')
    outputs, errors = [], []
    cases = read(run / 'val_cases/cases.json')
    warmup = 100
    records = read(reference / 'golden.json')['records']
    expected_rows = expected_packs = 0
    for record in records:
        with np.load(reference / (record['pair_key'] + '.npz'), allow_pickle=False) as arrays:
            count = len(arrays['left_final_boxes']) + len(arrays['right_final_boxes'])
            expected_rows += count
            expected_packs += count > 0
    with np.load(reference / (cases['performance_pair'] + '.npz'), allow_pickle=False) as arrays:
        warm_rows = len(arrays['left_final_boxes']) + len(arrays['right_final_boxes'])
    expected_rows += warmup * warm_rows
    expected_packs += warmup * (warm_rows > 0)
    defaults = dict(engine='b0', preprocess='c0', postprocess='a0')
    switches = {'R0': {}, 'R4_AB': dict(engine='graph', postprocess='a2'),
                'R5_ABC': dict(engine='graph', postprocess='a2', preprocess='c2')}
    for job in jobs:
        try:
            assert job['status'] == 'passed' and job['returncode'] == 0
            assert job['payload_sha256'] == fingerprint
            output = recovered / Path(job['output']).name
            value = compare(reference, output)
            assert value['status'] == 'passed' and value['pairs'] == 61 and not value['errors']
            assert len(value['arrays']) == 244 and all(v['exact'] and v['max_abs'] == 0 for v in value['arrays'])
            assert read(output / 'effective_runtime.json')['warmup_excluded'] == warmup
            hook = read(recovered / (output.name + '_hooks.json'))
            assert not hook.get('error') and not hook['validation_errors'] and len(hook['detectors']) == 1
            detector = hook['detectors'][0]
            assert detector['restore'] == 'complete' and not detector.get('restore_error')
            state = detector['before_restore']['components']
            for key, default in defaults.items():
                assert state[key]['effective'] == switches[job['name']].get(key, default)
                assert state[key]['fallback_count'] == 0 and state[key]['last_error'] is None
            if job['name'] != 'R0':
                graph, post = state['engine'], state['postprocess']
                assert graph['capture_count'] == 1 and graph['warmup_enqueue_count'] == 3
                assert graph['calls'] == graph['replay_count'] == graph['input_update_count'] == graph['output_clone_count'] == warmup + len(records)
                assert post['predict_calls'] == warmup + len(records)
                assert post['packed_batches'] == post['d2h_calls'] == expected_packs
                assert post['packed_rows'] == expected_rows and post['d2h_bytes'] == 24 * expected_rows
            if job['name'] == 'R5_ABC':
                pre = state['preprocess']
                assert pre['calls'] == pre['success_count'] == warmup + len(records)
                assert pre['host_buffer_allocations'] == pre['host_tensor_view_allocations'] == 1
                assert pre['host_buffer_bytes'] == 2457600 and pre['gpu_output_buffer_reused'] is False
            outputs.append(dict(name=job['name'], pairs=value['pairs'], arrays=len(value['arrays']),
                                tensors_exact=True, semantics_equal=True, restore='complete', components=state))
        except Exception as error:
            errors.append(dict(job=job['name'], error=repr(error)))
    return dict(status='passed_for_combination_benchmark' if not errors else 'failed_requires_review',
                errors=errors, phase_id=phase.name, correctness_manifest_sha256=fingerprint,
                jobs=outputs, pairs_per_variant=61, arrays_total=sum(v['arrays'] for v in outputs),
                candidate_source_commit=manifest['integration_commit'],
                allowed_matrix='combined_pipeline', allowed_variants=['R0', 'A2', 'R4_AB', 'R5_ABC'],
                C2_scope='R5 diagnostic comparison; no automatic adoption',
                semantics_tolerance=1e-10, tensors_requirement='exact values and full-file baseline hash references',
                physical_localization_accuracy_validated=False, performance_measured=False,
                stability_approved=False, production_approved=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--phase-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = review(args.run_dir, args.phase_dir)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k:result[k] for k in ['status','errors','pairs_per_variant','arrays_total']}, indent=2))
    raise SystemExit(bool(result['errors']))
