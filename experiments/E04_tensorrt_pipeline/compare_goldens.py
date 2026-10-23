#!/usr/bin/env python3
"""Compare frozen implementation outputs; never changes a reference."""
import argparse
import json
from pathlib import Path

import numpy as np


def compare_value(expected, actual, path='', tolerance=1e-10):
    errors = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(expected) != set(actual):
            return [path + ': fields differ']
        for key in expected:
            if path == 'diagnostics' and key in ('fps', 'det_ms'):
                continue
            errors.extend(compare_value(expected[key], actual[key], path + '.' + key if path else key, tolerance))
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return [path + ': length differs']
        for index, (a, b) in enumerate(zip(expected, actual)):
            errors.extend(compare_value(a, b, path + '[%d]' % index, tolerance))
    elif isinstance(expected, bool):
        if type(actual) is not bool or expected != actual:
            errors.append(path + ': boolean type/value differs')
    elif isinstance(expected, int):
        if type(actual) is not int or expected != actual:
            errors.append(path + ': integer type/value differs')
    elif isinstance(expected, float):
        if not isinstance(actual, (float, int)) or isinstance(actual, bool) or not np.isfinite([expected, actual]).all() or abs(expected - actual) > tolerance:
            errors.append(path + ': numeric difference')
    elif type(expected) is not type(actual) or expected != actual:
        errors.append(path + ': value differs')
    return errors


def compare(reference, candidate):
    left, right = [json.loads((p / 'golden.json').read_text()) for p in (reference, candidate)]
    errors, arrays = [], []
    runtimes = [json.loads((p / 'effective_runtime.json').read_text()) for p in (reference, candidate)]
    for key in ['engine_sha256', 'input_shape', 'bindings', 'effective_predictor_args', 'top_k', 'nms']:
        if runtimes[0][key] != runtimes[1][key]:
            errors.append('Runtime identity/configuration differs: ' + key)
    calibrations = [json.loads((p / 'calibration.json').read_text()) for p in (reference, candidate)]
    for key in ['K', 'baseline_m', 'image_size', 'fps']:
        if calibrations[0][key] != calibrations[1][key]:
            errors.append('Frozen calibration differs: ' + key)
    if left['pairs'] != right['pairs'] or len(left['records']) != len(right['records']):
        raise ValueError('Golden case count changed')
    for a, b in zip(left['records'], right['records']):
        errors.extend(a['pair_key'] + ': ' + x for x in compare_value(a, b))
        with np.load(reference / (a['pair_key'] + '.npz'), allow_pickle=False) as old, np.load(candidate / (a['pair_key'] + '.npz'), allow_pickle=False) as new:
            if set(old.files) != set(new.files):
                errors.append(a['pair_key'] + ': array names differ')
                continue
            for key in old.files:
                x, y = old[key], new[key]
                same_shape = x.shape == y.shape and x.dtype == y.dtype
                finite = same_shape and np.isfinite(y).all()
                exact = finite and np.array_equal(x, y)
                # Same Engine and FP32 preprocessing arithmetic are retained.
                # Any numerical difference needs review before performance tests.
                arrays.append(dict(pair_key=a['pair_key'], array=key, exact=bool(exact),
                                   max_abs=float(np.max(np.abs(x - y))) if finite and x.size else 0.0 if finite else None))
                if not exact:
                    errors.append(a['pair_key'] + ': ' + key + ' tensor differs')
    return dict(status='passed' if not errors else 'failed_requires_review', pairs=len(left['records']),
                arrays=arrays, semantic_tolerance=1e-10, tensor_requirement='bitwise exact on same device', errors=errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.reference, args.candidate)
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({k: result[k] for k in ['status', 'pairs', 'errors']}, ensure_ascii=False))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
