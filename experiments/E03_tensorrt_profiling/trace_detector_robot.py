#!/usr/bin/env python3
"""Isolated replay of installed detector: no camera, ROS node or model export."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import time


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--engine',type=Path,required=True)
    p.add_argument('--left',type=Path,required=True)
    p.add_argument('--right',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--trace',action='store_true')
    p.add_argument('--iterations',type=int,default=60)
    p.add_argument('--seconds',type=float,default=0)
    a=p.parse_args();assert not a.output.exists()
    import cv2
    import numpy as np
    import torch
    from ultralytics import YOLO
    from soccer_perception.adapters.yolo import YoloBallDetector, _install_torchvision_nms_fallback
    _install_torchvision_nms_fallback()
    frames=[cv2.imread(str(a.left)),cv2.imread(str(a.right))]
    assert all(x is not None for x in frames)
    # Attach the frozen existing engine directly to the installed adapter. Avoid
    # model-artifact creation/sidecars and never call PipelineFactory.create().
    detector=YoloBallDetector(a.engine,.45,640,'cuda:0',[0],True,tensorrt=True,engine_path=a.engine,trt_batch=2)
    detector.model=YOLO(str(a.engine),task='detect');detector.runtime_model_path=a.engine;detector.names={0:'football'}
    original_predict=detector.model.predict
    def predict(*args,**kwargs):
        kwargs.update(imgsz=(640,640),rect=False)
        return original_predict(*args,**kwargs)
    detector.model.predict=predict
    for _ in range(30):detector.detect_candidates_batch(frames,top_k=5)
    stage_samples=defaultdict(list)
    def wrap(obj,name,label):
        original=getattr(obj,name)
        def measured(*args,**kwargs):
            if a.trace:torch.cuda.nvtx.range_push(label)
            begin=time.monotonic_ns()
            try:return original(*args,**kwargs)
            finally:
                stage_samples[label].append((time.monotonic_ns()-begin)/1e6)
                if a.trace:torch.cuda.nvtx.range_pop()
        setattr(obj,name,measured)
    predictor=detector.model.predictor
    for name in ['preprocess','inference','postprocess']:wrap(predictor,name,'detector_'+name)
    wrap(detector,'_result_to_candidates','detector_candidates_to_cpu')
    if a.trace:torch.cuda.profiler.start();torch.cuda.nvtx.range_push('E03_steady_window')
    samples=[];begin=time.monotonic();i=0
    while i<a.iterations or time.monotonic()-begin<a.seconds:
        if a.trace:torch.cuda.nvtx.range_push('E03_iteration_%04d' % i)
        start=time.monotonic_ns();values=detector.detect_candidates_batch(frames,top_k=5);end=time.monotonic_ns()
        if a.trace:torch.cuda.nvtx.range_pop()
        samples.append(dict(iteration=i,wall_ms=(end-start)/1e6,candidates=[len(v) for v in values]));i+=1
    if a.trace:torch.cuda.nvtx.range_pop();torch.cuda.profiler.stop()
    def stats(v):
        return dict(n=len(v),mean=float(np.mean(v)),p50=float(np.percentile(v,50)),p95=float(np.percentile(v,95)),p99=float(np.percentile(v,99)))
    a.output.write_text(json.dumps(dict(engine=str(a.engine),source='installed soccer_perception.adapters.yolo.YoloBallDetector',
        scope='offline fixed Val pair; no camera/ROS/stereo/tracking/visualization; not system Hz',
        software=dict(torch=torch.__version__,opencv=cv2.__version__),
        image_shapes=[list(x.shape) for x in frames],warmup_excluded=30,trace=a.trace,
        detector_wall_ms=stats([r['wall_ms'] for r in samples]),
        method_wall_ms={k:stats(v) for k,v in stage_samples.items()},
        method_wall_ms_per_batch={k:stats(np.asarray(v).reshape(len(samples),-1).sum(axis=1)) if len(v)%len(samples)==0 else None for k,v in stage_samples.items()},
        note='Method ranges exclude any framework synchronization outside those methods; async ranges must not be summed as exclusive device cost.',
        records=samples,method_records=stage_samples),indent=2)+'\n')


if __name__=='__main__':main()
