"""One offline preprocessing race. No camera, ROS publishing, export or config writes."""
import argparse
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time

PROJECT = Path('/home/nvidia/soccer_backend_tensorrt')
OLD = PROJECT/'results/E04_tensorrt_pipeline/20261022T020842Z_78f1b7'


def save(path, value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    temporary.replace(path)


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def stats(values):
    import numpy as np
    return dict(n=len(values),mean=float(np.mean(values)),p95=float(np.percentile(values,95)),
                p99=float(np.percentile(values,99)))


def choose_candidate(rows,valid):
    all_stats={name:stats([r['input_ready_ms'] for r in rows if r['variant']==name]) for name in ['R0']+valid}
    paired={}
    for name in valid:
        savings=[];drifts=[];tail_savings=[]
        for block in range(4):
            subset=[r for r in rows if r['block']==block]
            baseline=[r for r in subset if r['variant']=='R0'];ends=sorted(set(r['position'] for r in baseline))
            references=[stats([r['input_ready_ms'] for r in baseline if r['position']==p]) for p in ends]
            means=[reference['mean'] for reference in references]
            target=stats([r['input_ready_ms'] for r in subset if r['variant']==name])
            savings.append(sum(means)/2-target['mean']);drifts.append(abs(means[1]-means[0]))
            tail_savings.append({key:sum(r[key] for r in references)/2-target[key] for key in ('p95','p99')})
        mean_saved=sum(savings)/4
        tail_ok=all(row[key]>=0 for row in tail_savings for key in ('p95','p99'))
        paired[name]=dict(saved_ms_by_block=savings,mean_saved_ms=mean_saved,baseline_abs_drift_ms=drifts,
                          saved_tail_ms_by_block=tail_savings,tail_nonregression=tail_ok,
                          eligible=mean_saved>=1.0 and min(savings)>0 and max(drifts)<mean_saved and tail_ok)
    eligible=[name for name in valid if paired[name]['eligible']]
    winner=max(eligible,key=lambda name:paired[name]['mean_saved_ms']) if eligible else None
    return all_stats,paired,winner


def assert_idle():
    conflicts=[]
    for directory in Path('/proc').glob('[0-9]*'):
        if int(directory.name)==os.getpid():continue
        try:args=(directory/'cmdline').read_bytes().split(b'\0')
        except OSError:continue
        names=[Path(s.decode(errors='replace')).name for s in args if s]
        if any(name in {'trtexec','nsys','worker.py','benchmark_preprocess.py','race.py',
                        'soccer_perception_ros_node.py','candidate_entry.py','stage0_replay.py',
                        'run_performance_robot.py','run_correctness.py'} for name in names):
            conflicts.append(dict(pid=int(directory.name),program=names[0]))
    if conflicts:raise RuntimeError('GPU/vision job already active; nothing stopped: '+repr(conflicts))


def preflight(root):
    assert_idle()
    payload=json.loads((root/'payload_manifest.json').read_text())
    for relative,digest in payload.items():
        if sha(root/relative)!=digest:raise RuntimeError('Experiment payload changed: '+relative)
    expected=json.loads((root/'frozen.json').read_text())
    for relative,digest in expected['production_files'].items():
        if sha(PROJECT/relative)!=digest:
            raise RuntimeError('Deployment changed; refresh baseline before testing: '+relative)
    for path,digest in expected['library_files'].items():
        if sha(Path(path))!=digest:raise RuntimeError('Preprocessing library source changed: '+path)
    power=subprocess.run(['/usr/sbin/nvpmodel','-q'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                         universal_newlines=True)
    if 'NV Power Mode: MAXN' not in power.stdout:raise RuntimeError('Expected existing MAXN; no mode changed')
    import soccer_perception
    from soccer_perception.ros.node import config_from_ros_params
    cfg=config_from_ros_params()
    if cfg.yolo_optimization!='a2_graph':raise RuntimeError('R0 must keep existing A2+Graph')
    if (cfg.imgsz,cfg.yolo_trt_batch,cfg.yolo_trt_dynamic)!=(640,2,False):raise RuntimeError('Not frozen 640 batch2')
    if str(cfg.yolo_model)!=expected['engine_path'] or sha(cfg.yolo_model)!=expected['engine_sha256']:
        raise RuntimeError('Engine selection/content changed')
    return cfg,dict(power_query=power.stdout,package=soccer_perception.__file__,payload_files=payload,
                    frozen=expected,config={k:str(v) if isinstance(v,Path) else v for k,v in vars(cfg).items()})


def load_images():
    import cv2
    inputs=OLD/'inputs';cases=json.loads((inputs/'cases.json').read_text())
    if cases.get('split')!='val' or cases.get('test_accessed') is not False:raise RuntimeError('Val only')
    if not 50<=len(cases['pairs'])<=100:raise RuntimeError('Expected 50-100 frozen stereo pairs')
    images={};flags=Counter()
    for item in cases['images']:
        name=item['name'];path=inputs/'images'/name
        if Path(name).name!=name:raise ValueError('Non-local image name')
        if sha(path)!=item['image_sha256']:raise RuntimeError('Val hash mismatch '+name)
        image=cv2.imread(str(path),cv2.IMREAD_COLOR)
        if image is None:raise RuntimeError('Unreadable '+name)
        images[name]=image
        flags.update({k:int(v) for k,v in (item.get('known_flags') or {}).items()})
    if any(flags[k]==0 for k in ['Small','Occluded','Blurred','No Ball']):raise RuntimeError('Required coverage missing')
    calibration=json.loads((OLD/'stage0_golden_attempt1/calibration.json').read_text())
    pairs=[[images[item['left']],images[item['right']]] for item in cases['pairs']]
    return cases,images,calibration,pairs,dict(flags)


class Telemetry:
    def __init__(self,directory):
        self.stop=threading.Event();self.directory=directory;self.process=None
    def __enter__(self):
        def sample():
            paths=[Path('/sys/devices/17000000.ga10b/devfreq/17000000.ga10b/cur_freq'),
                   Path('/sys/devices/17000000.ga10b/load')]
            paths+=list(Path('/sys/class/thermal').glob('thermal_zone*/temp'))
            with (self.directory/'telemetry.jsonl').open('w') as stream:
                while not self.stop.is_set():
                    values={}
                    for p in paths:
                        try:values[str(p)]=p.read_text().strip()
                        except OSError:pass
                    stream.write(json.dumps(dict(utc_ns=time.time_ns(),monotonic_ns=time.perf_counter_ns(),raw=values))+'\n')
                    stream.flush();self.stop.wait(.5)
        self.thread=threading.Thread(target=sample,daemon=True);self.thread.start()
        self.log=(self.directory/'tegrastats.log').open('w')
        try:self.process=subprocess.Popen(['tegrastats','--interval','500'],stdout=self.log,stderr=subprocess.STDOUT)
        except OSError as exc:self.log.write(str(exc)+'\n')
        return self
    def __exit__(self,*args):
        self.stop.set();self.thread.join(timeout=2)
        if self.process is not None:
            self.process.terminate()
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.log.close()


def check_graph(detector):
    status=detector.optimization_status();components=status['state']['components']
    if components['engine']['effective']!='graph' or components['engine']['capture_count']!=1:
        raise RuntimeError('Graph not captured exactly once: '+repr(status))
    if any(item.get('fallback_count',0) for item in components.values()):raise RuntimeError('R0 hook fallback')
    if components['postprocess']['effective']!='a2':raise RuntimeError('A2 not effective')
    return status


def profile(detector,pairs):
    """Diagnostic CPU method walls, includes async submissions, never called kernel timing."""
    import cv2
    import numpy as np
    import torch
    pred=detector.model.predictor;original_resize=cv2.resize;original_pad=cv2.copyMakeBorder
    rows=[];nested={}
    def wrap(name,fn):
        def call(*args,**kwargs):
            start=time.perf_counter_ns()
            try:return fn(*args,**kwargs)
            finally:nested[name]=nested.get(name,0)+(time.perf_counter_ns()-start)/1e6
        return call
    cv2.resize=wrap('resize',original_resize);cv2.copyMakeBorder=wrap('padding',original_pad)
    try:
        with torch.inference_mode():
            for index in range(50):
                torch.cuda.synchronize();nested.clear();row={}
                def timed(name,fn):
                    start=time.perf_counter_ns();value=fn();row[name]=(time.perf_counter_ns()-start)/1e6;return value
                start=time.perf_counter_ns()
                transformed=timed('pre_transform',lambda:pred.pre_transform(pairs[index%len(pairs)]))
                value=timed('stack',lambda:np.stack(transformed))
                value=timed('rgb_chw_views',lambda:value[...,::-1].transpose(0,3,1,2))
                value=timed('contiguous_pack',lambda:np.ascontiguousarray(value))
                value=timed('from_numpy',lambda:torch.from_numpy(value))
                value=timed('to_device',lambda:value.to(pred.device))
                value=timed('float',lambda:value.float())
                value=timed('normalize',lambda:value.div_(255))
                torch.cuda.synchronize();row['input_ready_wall']=(time.perf_counter_ns()-start)/1e6
                row.update(nested);rows.append(row)
                pred.inference(value);torch.cuda.synchronize()
    finally:cv2.resize=original_resize;cv2.copyMakeBorder=original_pad
    return dict(scope='diagnostic CPU methods; nested resize/padding included in pre_transform; async method walls not kernel times',
                methods={key:stats([row[key] for row in rows]) for key in rows[0]})


def screen(detector,pairs,valid,directory,iterations):
    import torch
    from candidates import install
    pred=detector.model.predictor;rows=[];hooks=[]
    def activate(name):return None if name=='R0' else install(pred,name)
    # Discard 100 real-image warmups per method. Inference is outside prep timing
    # and keeps GPU load representative of the active A2+Graph detector.
    with torch.inference_mode():
        for name in ['R0']+valid:
            handle=activate(name)
            try:
                for i in range(100):pred.inference(pred.preprocess(pairs[i%len(pairs)]))
                torch.cuda.synchronize()
            finally:
                if handle:handle.restore()
        for block in range(4):
            order=valid if block%2==0 else list(reversed(valid))
            for position,name in enumerate(['R0']+order+['R0']):
                print('[screen] block=%d variant=%s'%(block,name),flush=True)
                handle=activate(name)
                try:
                    for i in range(10):pred.inference(pred.preprocess(pairs[i%len(pairs)]))
                    torch.cuda.synchronize()
                    start_event=torch.cuda.Event(enable_timing=True);end_event=torch.cuda.Event(enable_timing=True)
                    for i in range(iterations//4):
                        pair=pairs[(block*(iterations//4)+i)%len(pairs)]
                        torch.cuda.synchronize();utc=time.time_ns();start=time.perf_counter_ns()
                        start_event.record();value=pred.preprocess(pair)
                        submit=time.perf_counter_ns();end_event.record();end_event.synchronize()
                        ready=time.perf_counter_ns()
                        if tuple(value.shape)!=(2,3,640,640) or value.dtype!=torch.float32:raise RuntimeError('Input contract changed')
                        rows.append(dict(block=block,position=position,variant=name,sample=i,utc_ns=utc,
                                         input_ready_ms=(ready-start)/1e6,cpu_submit_ms=(submit-start)/1e6,
                                         cuda_event_span_ms=start_event.elapsed_time(end_event)))
                        pred.inference(value);torch.cuda.synchronize() # explicitly outside timed region
                    if handle:
                        info=handle.describe()
                        if info['fallback_count']:raise RuntimeError('Candidate fell back: '+repr(info))
                        hooks.append(dict(block=block,variant=name,state=info))
                finally:
                    if handle:handle.restore()
                check_graph(detector)
    with (directory/'screen_frames.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    all_stats,paired,winner=choose_candidate(rows,valid)
    return dict(stats=all_stats,paired=paired,winner=winner,hooks=hooks,
                selection_rule='Correctness exact, >=1ms mean saved per stereo pair, every block positive, max baseline drift < mean saved, P95/P99 nonregression in each block',
                timing='input-ready completed wall includes CPU resize/pad/pack/H2D/fp32/normalize; CUDA event span includes host gaps and transfers, not pure GPU kernel time',
                untimed_work='Graph inference and synchronization after each sample; no changes to A2/Graph implementation/config')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--iterations',type=int,default=400)
    args=parser.parse_args()
    if args.iterations not in range(300,501) or args.iterations%4:parser.error('iterations 300-500 divisible by 4')
    root=Path(__file__).resolve().parent.parent;args.out.mkdir(parents=True,exist_ok=False)
    state=dict(status='starting',production_modified=False,camera_opened=False,ros_published=False)
    save(args.out/'status.json',state)
    detector=None
    try:
        cfg,environment=preflight(root);cases,images,calibration,pairs,flags=load_images()
        environment['coverage_flags']=flags;environment['pairs']=len(pairs)
        import cv2,torch
        from soccer_perception.pipeline import PipelineFactory
        from correctness import run_correctness
        from candidates import install
        environment.update(opencv_threads=cv2.getNumThreads(),torch_threads=torch.get_num_threads())
        environment['thermal_zone_types']={str(p.parent/'temp'):p.read_text().strip() for p in Path('/sys/class/thermal').glob('thermal_zone*/type')}
        save(args.out/'environment.json',environment)
        # VPI is qualified in a separate process, before creating any TRT
        # context. A failed synchronization/timeout aborts this race safely.
        first=OLD/'inputs/images'/cases['pairs'][0]['left']
        subprocess.run([os.sys.executable,str(root/'tools/vpi_qualify.py'),str(first),
                        str(args.out/'vpi_qualification.json')],check=True,timeout=30)
        detector=PipelineFactory(cfg)._create_detector()
        with Telemetry(args.out):
            state['status']='correctness';save(args.out/'status.json',state);print('[correctness] 61 Val stereo pairs',flush=True)
            correct=run_correctness(detector,cfg,cases,images,calibration,install,args.out)
            entries={item['variant']:item for item in correct.get('variants',[])}
            if correct.get('errors') or not entries.get('R0',{}).get('passed'):
                raise RuntimeError('R0 correctness reference failed; see correctness.json')
            if any(not item.get('restore_passed',True) for item in entries.values()):
                raise RuntimeError('Correctness hook cleanup failed; no performance test started')
            valid=[name for name in ['canvas','reuse'] if name in correct.get('eligible_candidates',[])]
            if not valid:
                state.update(status='finishing',decision='no_correct_candidate',winner=None);return
            detector.load();check_graph(detector)
            state['status']='screen';save(args.out/'status.json',state)
            diagnostics=profile(detector,pairs);save(args.out/'diagnostic.json',diagnostics)
            result=screen(detector,pairs,valid,args.out,args.iterations)
            result['correctness']=correct;result['graph_final']=check_graph(detector)
            save(args.out/'summary.json',result)
            state.update(status='finishing',decision='system_ab_candidate' if result['winner'] else 'stop_resize_letterbox',winner=result['winner'])
    except BaseException as exc:
        state.update(status='failed',error=repr(exc));raise
    finally:
        try:
            if detector is not None:detector.close()
            if detector is not None:
                expected=json.loads((root/'frozen.json').read_text())
                for relative,digest in expected['production_files'].items():
                    if sha(PROJECT/relative)!=digest:raise RuntimeError('Production changed during run: '+relative)
                if sha(Path(expected['engine_path']))!=expected['engine_sha256']:raise RuntimeError('Engine changed during run')
                state['production_hashes_unchanged']=True
            state['cleanup_passed']=True
            if state['status']=='finishing':state['status']='complete'
        except BaseException as exc:
            state.update(status='failed',cleanup_error=repr(exc));raise
        finally:
            save(args.out/'status.json',state)
            if state['status']=='complete':print('[DONE] decision='+state['decision']+' winner='+str(state['winner']),flush=True)


if __name__=='__main__':main()
