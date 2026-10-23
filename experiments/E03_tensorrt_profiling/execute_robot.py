#!/usr/bin/env python3
"""E03 isolated robot builds and validation. No production configuration writes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def save(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(run, args, log, phase):
    item = dict(phase=phase, command=list(map(str, args)), started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    save(run/'stage_progress.json', item)
    begin = time.monotonic()
    with Path(log).open('x') as stream:
        result = subprocess.run(list(map(str, args)), stdout=stream, stderr=subprocess.STDOUT)
    item.update(returncode=result.returncode, elapsed_s=time.monotonic()-begin, log=str(log))
    with (run/'commands.jsonl').open('a') as stream:
        stream.write(json.dumps(item)+'\n')
    save(run/'stage_progress.json', item)
    if result.returncode:
        raise RuntimeError('Command failed: %s; see %s' % (phase, log))
    return item


def builds(run, wait_pid):
    if wait_pid:
        save(run/'stage_progress.json', dict(phase='waiting_for_legacy_benchmark', pid=wait_pid))
        while Path('/proc/%s/cmdline' % wait_pid).exists():
            cmd = Path('/proc/%s/cmdline' % wait_pid).read_bytes()
            if b'benchmark.py' not in cmd:
                break
            time.sleep(3)
    trt = '/usr/src/tensorrt/bin/trtexec'
    help_result = subprocess.run([trt, '--help'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (run/'trtexec_help.txt').write_text(help_result.stdout)
    inventory = []
    for tag in ['E01_baseline', 'E02_c3k2']:
        for kind, verbosity in [('perf', 'layer_names_only'), ('profile', 'detailed')]:
            directory = run/'builds'/(tag+'_'+kind)
            directory.mkdir()
            cache = directory/'timing.cache'
            if kind == 'profile':
                source = run/'builds'/(tag+'_perf')/'timing.cache'
                if source.exists():
                    shutil.copy2(str(source), str(cache))
                    shutil.copy2(str(source), str(directory/'timing_before.cache'))
            args = [trt, '--onnx='+str(run/'inputs'/(tag+'.onnx')),
                    '--saveEngine='+str(directory/'model.plan'), '--fp16',
                    '--inputIOFormats=fp32:chw', '--outputIOFormats=fp32:chw',
                    '--memPoolSize=workspace:2048', '--profilingVerbosity='+verbosity,
                    '--timingCacheFile='+str(cache), '--buildOnly', '--verbose',
                    '--dumpLayerInfo', '--exportLayerInfo='+str(directory/'layers.json')]
            item = command(run, args, directory/'build.log', 'B_build_'+tag+'_'+kind)
            plan = directory/'model.plan'
            item.update(path=str(plan), sha256=sha(plan), bytes=plan.stat().st_size,
                        onnx_sha256=sha(run/'inputs'/(tag+'.onnx')), verbosity=verbosity)
            inventory.append(item)
            save(run/'build_inventory.json', inventory)
    save(run/'build_complete.json', dict(status='complete', engines=inventory))


def correctness(run, project):
    os.environ['YOLO_AUTOINSTALL']='false'
    os.environ['YOLO_CONFIG_DIR']=str(run/'ultralytics-config')
    os.environ['MPLCONFIGDIR']=str(run/'matplotlib-config')
    import numpy as np
    import torch
    sys.path.insert(0, str(project/'tool/model_benchmark'))
    from worker import Engine
    from soccer_perception.adapters.yolo import _install_torchvision_nms_fallback
    _install_torchvision_nms_fallback()
    from ultralytics.utils.ops import non_max_suppression
    data = np.load(str(run/'inputs/val64.npz'))['images']
    assert data.shape == (64, 640, 640, 3) and data.dtype == np.uint8
    # Freeze tolerances before reading any output differences. These are diagnostic
    # export-equivalence checks, not a replacement for full Val AP.
    tolerances = dict(max_matched_box_coordinate_error_px=2.0, max_matched_score_error=0.03,
                      nms_conf=0.45, nms_iou=0.7, max_det=300, matching_iou=0.9,
                      full_val_required_for_promoting_candidate=True)
    save(run/'correctness/tolerances.json', tolerances)
    inventory = []
    for tag in ['E01_baseline', 'E02_c3k2']:
        outputs = {}
        for kind in ['legacy', 'perf', 'profile']:
            path = run/'legacy'/(tag+'.engine') if kind == 'legacy' else run/'builds'/(tag+'_'+kind)/'model.plan'
            engine = Engine(path, 'auto')
            engine.allocate(42)
            inspector = engine.engine.create_engine_inspector()
            import tensorrt as trt
            (run/'correctness'/(tag+'_'+kind+'_layers.json')).write_text(inspector.get_engine_information(trt.LayerInformationFormat.JSON))
            engine.info['profiling_verbosity'] = str(engine.engine.profiling_verbosity)
            save(run/'correctness'/(tag+'_'+kind+'_engine.json'), engine.info)
            result = []
            input_index = next(i for i,x in enumerate(engine.io) if x['input'])
            output_index = next(i for i,x in enumerate(engine.io) if not x['input'])
            for start in range(0,len(data),2):
                a=np.ascontiguousarray(data[start:start+2].transpose(0,3,1,2), dtype=np.float32)/255.0
                engine.tensors[input_index].copy_(torch.from_numpy(a).to('cuda:0'))
                torch.cuda.synchronize()
                engine.execute()
                result.append(engine.tensors[output_index].detach().cpu().numpy().copy())
            values=np.concatenate(result)
            assert list(values.shape)==[64,5,8400] and np.isfinite(values).all()
            np.save(str(run/'correctness'/(tag+'_'+kind+'_output.npy')), values)
            outputs[kind]=values
            del engine
            torch.cuda.empty_cache()
        reference=outputs['legacy']
        def detections(values):
            result=[]
            for i in range(0,len(values),2):
                result.extend([x.cpu().numpy() for x in non_max_suppression(torch.from_numpy(values[i:i+2].copy()), conf_thres=0.45, iou_thres=0.7, nc=1, max_det=300)])
            return result
        reference_dets=detections(reference)
        def iou(a,b):
            lo=np.maximum(a[:2],b[:2]);hi=np.minimum(a[2:4],b[2:4])
            inter=np.maximum(hi-lo,0).prod()
            return float(inter/max(1e-9,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter))
        for kind in ['perf','profile']:
            target=outputs[kind]; delta=np.abs(target-reference)
            dets=detections(target); count_changed=[]; unmatched=[]; boxes=[]; scores=[]
            for i,(old,new) in enumerate(zip(reference_dets,dets)):
                if len(old)!=len(new): count_changed.append(i)
                used=set()
                for box in old:
                    candidates=[(iou(box,candidate),j) for j,candidate in enumerate(new) if j not in used]
                    if not candidates: unmatched.append(i);continue
                    overlap,j=max(candidates)
                    if overlap<0.9: unmatched.append(i);continue
                    used.add(j); boxes.append(float(np.max(np.abs(box[:4]-new[j,:4]))));scores.append(float(abs(box[4]-new[j,4])))
            entry=dict(model=tag,kind=kind,images=64,raw_max_abs=float(delta.max()),raw_mean_abs=float(delta.mean()),
                       coordinate_abs_p99=float(np.percentile(delta[:,:4],99)),score_max_abs=float(delta[:,4].max()),
                       changed_detection_count_images=count_changed,unmatched_reference_images=sorted(set(unmatched)),
                       matched_detections=len(boxes),max_matched_box_coordinate_error_px=max(boxes or [0]),max_matched_score_error=max(scores or [0]),
                       legacy_detection_count=sum(map(len,reference_dets)),candidate_detection_count=sum(map(len,dets)))
            entry['passed']=not count_changed and not unmatched and max(boxes or [0])<=2 and max(scores or [0])<=0.03
            inventory.append(entry)
    save(run/'correctness/summary.json',dict(tolerances=tolerances,comparisons=inventory,passed=all(x['passed'] for x in inventory),scope='64 fixed Val images; no Test or full AP'))
    print(json.dumps(inventory,indent=2), flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('stage',choices=['build','correctness'])
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--project',type=Path,default=Path('/home/nvidia/soccer_backend_tensorrt'))
    p.add_argument('--wait-pid',type=int)
    a=p.parse_args()
    try:
        if a.stage=='build': builds(a.run,a.wait_pid)
        elif a.stage=='correctness': correctness(a.run,a.project)
    except BaseException as exc:
        save(a.run/('failed_'+a.stage+'.json'),dict(error=repr(exc),utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())))
        raise


if __name__=='__main__':
    main()
