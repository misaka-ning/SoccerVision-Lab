#!/usr/bin/env python3
"""B1/B2 correctness probe on the robot. This is not a latency benchmark."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import signal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    parent = os.getppid()
    if ctypes.CDLL(None).prctl(1, signal.SIGTERM) != 0 or parent == 1 or os.getppid() != parent:
        raise RuntimeError('Cannot establish parent-exit protection')
    args.output.mkdir(parents=True, exist_ok=False)
    import cv2
    import numpy as np
    import torch
    from soccer_perception.adapters.yolo import YoloBallDetector
    from soccer_perception.optimizations.graph import install
    engine = args.run_dir / 'frozen_models/E01_baseline.engine'
    reference = args.run_dir / 'stage0_golden_attempt1'
    records = json.loads((reference / 'golden.json').read_text())['records']
    detector = YoloBallDetector(engine, 0.45, 640, '0', [0], False,
                               tensorrt=True, engine_path=engine, trt_batch=2)
    detector.load()
    images = [cv2.imread(str(args.run_dir / 'inputs/images' / ('frame_001479_' + eye + '.png'))) for eye in ['left', 'right']]
    detector.detect_candidates_batch(images, top_k=5)
    backend = detector.model.predictor.model
    original = backend.forward
    handle = install(detector, 'graph')
    result = dict(status='running', scope='B1/B2 output/ownership correctness only; no performance claim', cases=[])
    try:
        with torch.inference_mode():
            # Ten fixed repeats followed by the complete changing-input sequence.
            sequence = records[:1] * 10 + records
            retained = None
            retained_host = None
            for index, record in enumerate(sequence):
                with np.load(reference / (record['pair_key'] + '.npz'), allow_pickle=False) as data:
                    im = torch.from_numpy(data['input'].copy()).to(backend.device)
                    frozen = data['raw'].copy()
                baseline = original(im).detach().cpu().numpy().copy()
                graph = backend.forward(im)
                handle.synchronize()
                actual = graph.detach().cpu().numpy().copy()
                unchanged = retained is None or np.array_equal(retained.detach().cpu().numpy(), retained_host)
                item = dict(case=index, pair_key=record['pair_key'], fixed_repeat=index < 10,
                            baseline_matches_frozen=bool(np.array_equal(baseline, frozen)),
                            graph_matches_current_baseline=bool(np.array_equal(actual, baseline)),
                            retained_previous_output_unchanged=bool(unchanged),
                            max_abs=float(np.max(np.abs(actual - baseline))))
                result['cases'].append(item)
                if not all(item[k] for k in ['baseline_matches_frozen', 'graph_matches_current_baseline', 'retained_previous_output_unchanged']):
                    raise RuntimeError('Graph/current-input/ownership mismatch: ' + repr(item))
                # Mimic external NMS modifying an output: the next result must
                # still match current input, and this tensor must remain owned.
                graph.add_(1.0)
                retained, retained_host = graph, graph.detach().cpu().numpy().copy()
            status = handle.describe()
            result['handle'] = status
            if status['effective'] != 'graph' or status['fallback_count'] or status['capture_count'] != 1 or status['replay_count'] != len(sequence) or status['input_update_count'] != len(sequence):
                raise RuntimeError('Graph did not execute every requested current input: ' + repr(status))
        result['status'] = 'passed'
    except BaseException as error:
        result.update(status='failed_requires_review', error=repr(error))
        raise
    finally:
        try:
            handle.restore()
            result['restore'] = 'complete'
        except Exception as error:
            result.update(status='failed_requires_review', restore_error=repr(error))
            raise
        finally:
            with (args.output / 'result.json').open('x') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write('\n')
    print(json.dumps({'status': result['status'], 'cases': len(result['cases'])}))


if __name__ == '__main__':
    main()
