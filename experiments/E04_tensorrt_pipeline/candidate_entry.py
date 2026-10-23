#!/usr/bin/env python3
"""Run an existing E04 replay/worker with opt-in hooks, in this process only."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import runpy
import signal
import sys
import types

ABSENT = object()


def frame_metrics(states, c1=False):
    values = {'a2_pack_method_ms': 0.0, 'left_candidates': 0, 'right_candidates': 0}
    for state in states:
        detector = state['detector']
        values['a2_pack_method_ms'] += getattr(getattr(detector, '_e04_postprocess_handle', None), 'last_pack_wall_ms', 0.0)
        counts = getattr(detector, '_e04_last_candidate_counts', {})
        for eye in ['left', 'right']:
            values[eye + '_candidates'] += counts.get(eye, 0)
        handle = getattr(detector.model.predictor, '_e04_preprocess_handle', None)
        if c1 and handle is not None:
            for key, item in handle.describe().get('timings', {}).items():
                values['c1_' + key + '_method_ms'] = item['last_ms']
    return values


def runtime_identity(detector):
    import torchvision
    predictor = detector.model.predictor
    backend = predictor.model
    return dict(input_shape=list(backend.bindings['images'].shape),
                bindings={k: dict(shape=list(v.shape), dtype=str(v.dtype)) for k, v in backend.bindings.items()},
                effective_predictor_args={k: getattr(predictor.args, k, None) for k in
                    ['conf', 'iou', 'classes', 'agnostic_nms', 'max_det', 'rect', 'half', 'imgsz']},
                nms=dict(module=torchvision.ops.nms.__module__, name=torchvision.ops.nms.__name__))


def patch_detector(detector_type, installer, variants):
    original = detector_type.detect_candidates_batch
    states = []

    def detect(self, *args, **kwargs):
        state = next((s for s in states if s['detector'] is self), None)
        if state is None:
            # Startup only: initialize the real predictor/backend on this batch.
            # Discard this result, install, then execute the same current batch.
            # The caller's first warmup iteration is therefore a candidate call.
            original(self, *args, **kwargs)
            handle = installer(self, variants)
            # The existing replay adds timing/Golden wrappers after warmup.
            # Save this boundary so those owned wrappers can be removed before
            # handle.restore checks that its own installed methods still match.
            predictor = self.model.predictor
            boundary = [(obj, name, vars(obj).get(name, ABSENT)) for obj, name in
                        [(self, '_result_to_candidates'), (predictor, 'preprocess'),
                         (predictor, 'inference'), (predictor, 'postprocess')]]
            states.append(dict(detector=self, handle=handle, replay_boundary=boundary))
        result = original(self, *args, **kwargs)
        if isinstance(result, (list, tuple)) and len(result) == 2 and all(isinstance(v, list) for v in result):
            self._e04_last_candidate_counts = dict(left=len(result[0]), right=len(result[1]))
        return result

    detector_type.detect_candidates_batch = detect
    return original, states


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry', type=Path, required=True)
    parser.add_argument('--variant-json', type=Path, required=True)
    parser.add_argument('--status-file', type=Path, required=True)
    parser.add_argument('--frozen-calibration', type=Path, help='Golden replay only: use baseline intrinsics, without opening camera')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    parent = os.getppid()
    if ctypes.CDLL(None).prctl(1, signal.SIGTERM) != 0 or parent == 1 or os.getppid() != parent:
        raise RuntimeError('Cannot establish parent-exit protection')
    if args.status_file.exists():
        raise FileExistsError('Never overwrite an earlier hook status')
    variants = json.loads(args.variant_json.read_text())
    from soccer_perception.adapters.yolo import YoloBallDetector
    from soccer_perception.optimizations import install_pipeline
    original, states = patch_detector(YoloBallDetector, install_pipeline, variants)
    entry = args.entry.resolve()
    sys.path.insert(0, str(entry.parent))
    argv = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    sys.argv = [str(entry)] + argv
    report = dict(requested=variants, initialization='one excluded original call, then every caller warmup uses candidate', detectors=[])
    packet_observer = None
    def checkpoint():
        report['warmup_checkpoint'] = json.loads(json.dumps([s['handle'].describe() for s in states]))
        report['runtime_identity'] = [runtime_identity(s['detector']) for s in states]
        if packet_observer is not None:
            report['packet_observer_warmup_calls'] = packet_observer.calls
    zed_module = original_zed = None
    try:
        if args.frozen_calibration:
            if entry.name != 'stage0_replay.py' or '--mode' not in argv or argv[argv.index('--mode') + 1] != 'golden':
                raise ValueError('Frozen calibration is only valid for offline Golden replay')
            import numpy as np
            import soccer_perception.adapters.zed as zed_module
            from soccer_perception.types import CameraIntrinsics
            calibration = json.loads(args.frozen_calibration.read_text())
            class FrozenCalibration:
                def __init__(self, config): pass
                def open(self):
                    return CameraIntrinsics(K=np.asarray(calibration['K'], dtype=np.float64),
                        baseline_m=calibration['baseline_m'], image_size=tuple(calibration['image_size']), fps=calibration['fps'])
                def close(self): pass
            original_zed = zed_module.ZedFrameSource
            zed_module.ZedFrameSource = FrozenCalibration
            report['frozen_calibration'] = str(args.frozen_calibration)
        module = runpy.run_path(str(entry), run_name='e04_existing_entry')
        function = module['main']
        if entry.name == 'stage0_replay.py':
            original_write = function.__globals__['write_json']
            def write(path, value):
                if Path(path).name == 'effective_runtime.json':
                    checkpoint()
                    value = dict(value, e04_hooks=[s['handle'].describe() for s in states],
                                 graph_status='See e04_hooks and final candidate status; original backend is wrapped when requested')
                return original_write(path, value)
            function.__globals__['write_json'] = write
            # A2 moves packing into model.predict; keep a per-frame method wall
            # next to the existing converter wall rather than claiming it vanished.
            original_csv = function.__globals__['csv']
            class ReplayRecords(original_csv.DictWriter):
                def __init__(self, stream, fields, **kwargs):
                    extra = ['a2_pack_method_ms']
                    if variants.get('preprocess') == 'c1':
                        extra += ['c1_' + key + '_method_ms' for key in ['pre_transform', 'stack', 'color_layout_views', 'contiguous_pack', 'from_numpy', 'to_device', 'dtype', 'normalize']]
                    super().__init__(stream, list(fields) + extra, **kwargs)
                def writerow(self, row):
                    if isinstance(row.get('sample'), int):
                        extra = frame_metrics(states, c1=variants.get('preprocess') == 'c1')
                        row = dict(row, **{k: v for k, v in extra.items() if k in self.fieldnames})
                    return super().writerow(row)
            function.__globals__['csv'] = types.SimpleNamespace(DictWriter=ReplayRecords)
        elif entry.name == 'worker.py':
            import soccer_perception.ros.node as observed_node
            from packet_observer import FIELDS as packet_fields, install_node_payload_observer
            packet_observer = install_node_payload_observer(observed_node)
            original_records = function.__globals__['Records']
            class SystemRecords(original_records):
                def __init__(self, directory, fields):
                    super().__init__(directory, list(fields) + ['a2_pack_method_ms', 'left_candidates', 'right_candidates'] + list(packet_fields))
                def add(self, row, metric):
                    if not packet_observer.last_metrics:
                        raise RuntimeError('No matching packet observation before recording this cycle')
                    row = dict(row, **frame_metrics(states), **packet_observer.last_metrics)
                    return super().add(row, metric)
            original_progress = function.__globals__['Progress']
            class SystemProgress(original_progress):
                def set(self, stage, force=False, **values):
                    if stage == '测量' and values.get('completed') == 0 and 'warmup_checkpoint' not in report:
                        checkpoint()
                    return super().set(stage, force=force, **values)
            function.__globals__.update(Records=SystemRecords, Progress=SystemProgress)
        return function()
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        YoloBallDetector.detect_candidates_batch = original
        if original_zed is not None:
            zed_module.ZedFrameSource = original_zed
        failures = []
        if not states:
            failures.append('No initialized detector/hook state recorded')
        for state in states:
            item = {}
            try:
                item['before_restore'] = state['handle'].describe()
                for key, value in item['before_restore']['components'].items():
                    if value.get('fallback_count', 0) or value.get('effective') != variants.get(key, {'engine': 'b0', 'postprocess': 'a0', 'preprocess': 'c0'}[key]):
                        failures.append(key + ' did not execute the requested variant without fallback')
                    if key == 'engine' and variants.get(key) == 'graph':
                        if value.get('capture_count') != 1 or not value.get('replay_count') or value.get('replay_count') != value.get('input_update_count'):
                            failures.append('Graph capture/replay/input-update counters invalid')
            except Exception as error:
                item['snapshot_error'] = repr(error)
                failures.append('Hook snapshot failed: ' + repr(error))
            try:
                if entry.name == 'stage0_replay.py':
                    for obj, name, value in state['replay_boundary']:
                        if value is ABSENT:
                            vars(obj).pop(name, None)
                        else:
                            setattr(obj, name, value)
                state['handle'].restore()
                item['restore'] = 'complete'
            except Exception as error:
                item['restore_error'] = repr(error)
                failures.append('Restore failed: ' + repr(error))
            report['detectors'].append(item)
        if packet_observer is not None:
            observed = dict(calls=packet_observer.calls, warmup_calls=report.get('packet_observer_warmup_calls'),
                            fields=list(packet_fields), payload_mutated=False,
                            timestamp_scope='source read-time relative clock; not SDK exposure time')
            try:
                packet_observer.restore()
                observed['restore'] = 'complete'
            except Exception as error:
                observed['restore_error'] = repr(error)
                failures.append('Packet observer restore failed: ' + repr(error))
            report['packet_observer'] = observed
        report['validation_errors'] = failures
        with args.status_file.open('x') as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
        if failures:
            raise RuntimeError('Candidate hook verification failed: ' + repr(failures))


if __name__ == '__main__':
    raise SystemExit(main())
