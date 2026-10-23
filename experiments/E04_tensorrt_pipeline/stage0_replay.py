#!/usr/bin/env python3
"""Robot-only Golden capture or fixed-pair baseline. Long runs are user launched."""
import argparse
import csv
from dataclasses import replace
import json
from pathlib import Path
import time

from audit_robot import EXPECTED_E01, sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=['golden', 'detector'], required=True)
    parser.add_argument('--warmup', type=int, default=100)
    parser.add_argument('--seconds', type=float, default=60)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    if run not in args.output.resolve().parents:
        raise ValueError('Output must be inside this E04 run')
    args.output.mkdir(parents=True, exist_ok=False)
    engine = run / 'frozen_models/E01_baseline.engine'
    if sha256(engine) != EXPECTED_E01:
        raise ValueError('Frozen E01 Engine identity changed')
    import cv2
    import numpy as np
    import torch
    import torchvision
    import tensorrt
    from soccer_perception.adapters.yolo import YoloBallDetector, parse_int_list
    from soccer_perception.adapters.zed import ZedFrameSource
    from soccer_perception.ros.node import config_from_ros_params
    from soccer_perception.ros.output import build_ball_position_camera_payload, build_ball_camera_diagnostics
    from soccer_perception.pipeline import SoccerPerceptionPipeline
    from soccer_perception.core.tracking import AlphaBetaBallTracker
    from soccer_perception.types import StereoFrame, json_safe

    original_config = config_from_ros_params()
    config = replace(original_config, yolo_model=engine, yolo_engine_path=engine,
                     yolo_tensorrt=True, yolo_trt_batch=2, imgsz=640, zed_viser_enabled=False)
    manifest = json.loads((run / 'inputs/cases.json').read_text())
    if manifest['split'] != 'val' or manifest['test_accessed'] is not False:
        raise ValueError('Expected fixed Val cases')
    for record in manifest['images']:
        if sha256(run / 'inputs/images' / record['name']) != record['image_sha256']:
            raise ValueError('Val image changed: ' + record['name'])

    def frames(pair):
        result = [cv2.imread(str(run / 'inputs/images' / pair[side])) for side in ['left', 'right']]
        if any(x is None for x in result):
            raise RuntimeError('Could not decode Val pair ' + pair['pair_key'])
        return result

    perf_pair = next(x for x in manifest['pairs'] if x['pair_key'] == manifest['performance_pair'])
    fixed = frames(perf_pair)
    detector = YoloBallDetector(engine, config.det_conf, config.imgsz, config.device,
                               parse_int_list(config.yolo_class_ids), config.half,
                               tensorrt=True, engine_path=engine, trt_batch=2)
    detector.load()
    # Static TensorRT disables rectangular auto-padding; make E03's test setting explicit.
    original_predict = detector.model.predict
    def predict(*values, **kwargs):
        kwargs.update(imgsz=(640, 640), rect=False)
        return original_predict(*values, **kwargs)
    detector.model.predict = predict
    for _ in range(args.warmup):
        detector.detect_candidates_batch(fixed, top_k=config.yolo_top_k)
    predictor = detector.model.predictor
    backend = predictor.model
    actual_shape = list(backend.bindings['images'].shape)
    if not backend.engine or actual_shape != [2, 3, 640, 640]:
        raise ValueError('Actual backend/input shape changed: ' + str(actual_shape))
    metadata = dict(engine_sha256=EXPECTED_E01, source='installed YoloBallDetector public detect_candidates_batch',
                    runtime_model=str(detector.runtime_model_path), input_shape=actual_shape,
                    bindings={k: dict(shape=list(v.shape), dtype=str(v.dtype)) for k, v in backend.bindings.items()},
                    effective_predictor_args={k: getattr(predictor.args, k, None) for k in
                        ['conf', 'iou', 'classes', 'agnostic_nms', 'max_det', 'rect', 'half', 'imgsz']},
                    top_k=config.yolo_top_k, nms=dict(module=torchvision.ops.nms.__module__, name=torchvision.ops.nms.__name__),
                    graph_status='no Graph path in audited AutoBackend.forward; direct execute_v2',
                    torch=torch.__version__, torchvision=torchvision.__version__, tensorrt=tensorrt.__version__,
                    opencv=cv2.__version__, warmup_excluded=args.warmup,
                    original_config={k: str(v) if isinstance(v, Path) else v for k, v in vars(original_config).items()})
    write_json(args.output / 'effective_runtime.json', metadata)
    expected_args = dict(conf=0.45, iou=0.7, classes=[0], max_det=300, agnostic_nms=False)
    if any(metadata['effective_predictor_args'][k] != v for k, v in expected_args.items()) or config.yolo_top_k != 5:
        raise ValueError('Effective detector parameters differ from the reviewed baseline')
    if metadata['nms']['name'] != 'nms_fallback':
        raise ValueError('NMS implementation changed since audit; review it before establishing the baseline')

    if args.mode == 'detector':
        stage = {}
        calls = []
        def wrap(obj, name, label):
            original = getattr(obj, name)
            def measured(*values, **kwargs):
                start = time.perf_counter_ns()
                try:
                    return original(*values, **kwargs)
                finally:
                    stage[label] = stage.get(label, 0.0) + (time.perf_counter_ns() - start) / 1e6
            setattr(obj, name, measured)
        for name in ['preprocess', 'inference', 'postprocess']:
            wrap(predictor, name, name + '_method_ms')
        wrap(detector, '_result_to_candidates', 'candidates_to_cpu_method_ms')
        with (args.output / 'frames.csv').open('w', newline='', buffering=1) as stream:
            fields = ['sample', 'detector_wall_ms', 'preprocess_method_ms', 'inference_method_ms',
                      'postprocess_method_ms', 'candidates_to_cpu_method_ms', 'left_candidates', 'right_candidates']
            writer = csv.DictWriter(stream, fields); writer.writeheader()
            begin = time.monotonic()
            while time.monotonic() - begin < args.seconds:
                stage.clear()
                start = time.perf_counter_ns()
                values = detector.detect_candidates_batch(fixed, top_k=config.yolo_top_k)
                row = dict(sample=len(calls), detector_wall_ms=(time.perf_counter_ns() - start) / 1e6,
                           left_candidates=len(values[0]), right_candidates=len(values[1]), **stage)
                writer.writerow(row); calls.append(row['detector_wall_ms'])
        write_json(args.output / 'result.json', dict(status='complete', samples=len(calls), seconds=args.seconds,
                    scope='Fixed native E03 Val pair; method walls include async/waits, not pure CPU or exclusive GPU cost; no camera/ROS'))
        return

    # Actual camera calibration is captured only during the user-run safe test window.
    source = ZedFrameSource(original_config)
    try:
        intrinsics = source.open()
    finally:
        source.close()
    write_json(args.output / 'calibration.json', dict(K=intrinsics.K.tolist(), baseline_m=intrinsics.baseline_m,
                image_size=list(intrinsics.image_size), fps=intrinsics.fps,
                scope='Current ZED calibration used for implementation-equivalence replay, not Val physical depth ground truth'))
    class ReplaySource:
        def __init__(self): self.index = 0
        def open(self): return intrinsics
        def close(self): pass
        def read(self):
            if self.index >= len(manifest['pairs']): return None
            pair = manifest['pairs'][self.index]; left, right = frames(pair)
            if [left.shape[1], left.shape[0]] != list(intrinsics.image_size):
                raise ValueError('Val dimensions differ from calibration resolution; no implicit calibration rescaling')
            value = StereoFrame(timestamp=1000.0 + self.index / float(intrinsics.fps),
                                left=left, right=right, frame_idx=self.index)
            self.index += 1
            return value
    class NullVisualizer:
        def open(self): pass
        def close(self): pass
        def update(self, *values): pass
    # Model has already been loaded/warmed above; pipeline.open must not reload it.
    detector.load = lambda: None
    capture = {}
    original_pre = predictor.preprocess
    original_infer = predictor.inference
    original_post = predictor.postprocess
    def pre(*values, **kwargs):
        result = original_pre(*values, **kwargs)
        if result.dtype != torch.float32 or list(result.shape) != [2, 3, 640, 640]:
            raise ValueError('Preprocessed input changed from fixed FP32 batch2/640')
        capture['input'] = result.detach().cpu().numpy().copy()
        return result
    def infer(*values, **kwargs):
        result = original_infer(*values, **kwargs)
        raw = result[0] if isinstance(result, (tuple, list)) and len(result) == 1 else result
        if not isinstance(raw, torch.Tensor) or raw.dtype != torch.float32 or list(raw.shape) != [2, 5, 8400]:
            raise ValueError('Raw Engine output semantics differ from frozen one-to-many [2,5,8400]')
        # Snapshot before NMS can modify its view of raw coordinates.
        capture['raw'] = raw.detach().cpu().numpy().copy()
        return result
    def post(*values, **kwargs):
        result = original_post(*values, **kwargs)
        capture['final_boxes'] = [x.boxes.data.detach().cpu().numpy().copy() for x in result]
        return result
    predictor.preprocess, predictor.inference, predictor.postprocess = pre, infer, post
    original_candidates = detector.detect_candidates_batch
    def candidates(*values, **kwargs):
        result = original_candidates(*values, **kwargs)
        capture['candidates'] = [[x.to_dict() for x in group] for group in result]
        return result
    detector.detect_candidates_batch = candidates
    tracker = AlphaBetaBallTracker(max_coast_frames=config.max_coast_frames,
                                   max_coast_time_s=config.max_coast_time_s, velocity_decay=config.velocity_decay)
    pipeline = SoccerPerceptionPipeline(ReplaySource(), detector, tracker, config, visualizer=NullVisualizer())
    records = []
    pipeline.open()
    try:
        for index, pair in enumerate(manifest['pairs']):
            capture.clear(); packet = pipeline.next_packet()
            if packet is None: raise RuntimeError('Premature EOF')
            np.savez_compressed(args.output / (pair['pair_key'] + '.npz'), input=capture['input'], raw=capture['raw'],
                                left_final_boxes=capture['final_boxes'][0], right_final_boxes=capture['final_boxes'][1])
            records.append(dict(pair_key=pair['pair_key'], frame_idx=packet.frame_idx, replay_timestamp=packet.timestamp,
                                candidates=capture['candidates'], selected=[x.to_dict() if x else None for x in [packet.left_det, packet.right_det]],
                                measurement=packet.ball_3d_measurement.to_dict(), track=packet.camera_track_state.to_dict(),
                                ros_payload=build_ball_position_camera_payload(packet), diagnostics=json_safe(build_ball_camera_diagnostics(packet))))
    finally:
        pipeline.close()
    write_json(args.output / 'golden.json', dict(status='complete', split='val', test_accessed=False, pairs=len(records),
                timestamps='Deterministic replay clock 1000 + frame_idx/camera_fps; original capture timestamps unavailable',
                exclude_from_semantic_equality=['diagnostics.fps', 'diagnostics.det_ms'], records=records))
    write_json(args.output / 'result.json', dict(status='complete', pairs=len(records), golden_reference=True,
                note='No performance conclusion from Golden capture; extra CPU copies are intentional diagnostics'))


if __name__ == '__main__':
    main()
