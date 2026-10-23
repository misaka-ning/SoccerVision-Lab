#!/usr/bin/env python3
"""Continue E03 after serialized builds; all outputs are confined to one run."""
import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from execute_robot import command, save, sha


def summaries(run, folder):
    result=[]
    for path in sorted((run/folder).glob('*/summary.json')):
        data=json.loads(path.read_text())
        if data['status']=='complete' and data['summary']:
            result.append((path,data))
    return result[-1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--project',type=Path,default=Path('/home/nvidia/soccer_backend_tensorrt'))
    parser.add_argument('--resume-after-correctness',action='store_true')
    parser.add_argument('--attempt',type=int,default=1)
    args=parser.parse_args();run=args.run;project=args.project
    while not (run/'build_complete.json').exists():
        if (run/'failed_build.json').exists():
            raise RuntimeError('Build stage failed')
        time.sleep(3)
    if not args.resume_after_correctness:
        command(run,[sys.executable,run/'scripts/execute_robot.py','correctness','--run',run],
                run/'correctness/stage.log','B_correctness')
    else:
        for item in json.loads((run/'build_inventory.json').read_text()):
            assert sha(item['path'])==item['sha256'], 'Engine changed since correctness check'
    correctness=json.loads((run/'correctness/summary.json').read_text())
    if not correctness['passed']:
        raise RuntimeError('Correctness gate did not pass; inspect per-model comparisons before timings')
    # The existing controller requires an .engine suffix even in raw-engine mode.
    # Hard links preserve exactly the already-validated plan bytes; they do not
    # add or pretend to contain an Ultralytics metadata header.
    aliases=[]
    for src in sorted((run/'builds').glob('*/model.plan')):
        dest=src.with_suffix('.engine')
        if not dest.exists():os.link(str(src),str(dest))
        assert sha(src)==sha(dest)
        aliases.append(dict(raw_plan=str(src),engine_mode_alias=str(dest),sha256=sha(src),metadata_header=False))
    save(run/'raw_engine_aliases.json',aliases)
    suffix='' if args.attempt==1 else '_attempt%d'%args.attempt
    import yaml
    cfg=yaml.safe_load((run/'config_legacy.yaml').read_text())
    cfg['models']=[dict(name=name,path=str(run/'builds'/(tag+'_perf')/'model.engine'))
                   for name,tag in [('E1_perf','E01_baseline'),('E2_perf','E02_c3k2')]]
    cfg['baseline']='E1_perf';cfg['output']['directory']=str(run/'standard_benchmark')
    path=run/('config_standard'+suffix+'.yaml');path.write_text(yaml.safe_dump(cfg,sort_keys=False,allow_unicode=True))
    command(run,['bash',project/'tool/model_benchmark/run.sh','--config',path],run/('standard_benchmark'+suffix+'.log'),'C_standard_benchmark')
    # Profile artifacts are diagnostic controls, not another full performance
    # matrix. A normal 60 s pass tests their relation to the three-round controls;
    # add repetitions only if actual discrepancies require investigation.
    cfg['models']=[dict(name=name,path=str(run/'builds'/(tag+'_profile')/'model.engine'))
                   for name,tag in [('E1_profile','E01_baseline'),('E2_profile','E02_c3k2')]]
    cfg['baseline']='E1_profile';cfg['test']['rounds']=1
    cfg['output']['directory']=str(run/'profile_benchmark')
    profile_cfg=run/('config_profile_check'+suffix+'.yaml');profile_cfg.write_text(yaml.safe_dump(cfg,sort_keys=False,allow_unicode=True))
    command(run,['bash',project/'tool/model_benchmark/run.sh','--config',profile_cfg],run/('profile_benchmark'+suffix+'.log'),'C_profile_normal_check')
    legacy_path,legacy=summaries(run,'legacy_benchmark')
    standard_path,standard=summaries(run,'standard_benchmark')
    profile_path,profile_summary=summaries(run,'profile_benchmark')
    checkpoint=dict(legacy_summary=str(legacy_path),standard_summary=str(standard_path),correctness=correctness,
                    legacy=legacy,standard=standard,profile_normal_summary=str(profile_path),profile_normal=profile_summary,
                    interpretation='Compare normal timing across builds before applying new-engine profile to legacy; no channel search.')
    save(run/'checkpoint_AC.json',checkpoint)
    trt='/usr/src/tensorrt/bin/trtexec'
    input_flag='--loadInputs=images:'+str(run/'inputs/representative_batch2.bin')
    # Core D: all six independent profiles, after correctness and normal timing.
    for repeat in range(1,4):
        for tag in ['E01_baseline','E02_c3k2']:
            directory=run/'profiles'/('%s_r%d' % (tag,repeat));directory.mkdir()
            command(run,[trt,'--loadEngine='+str(run/'builds'/(tag+'_profile')/'model.plan'),
                         '--streams=1','--warmUp=2000','--duration=10','--iterations=200','--noDataTransfers',input_flag,
                         '--separateProfileRun','--dumpProfile','--exportProfile='+str(directory/'profile.json'),
                         '--dumpLayerInfo','--exportLayerInfo='+str(directory/'layers.json')],
                    directory/'profile.log','D_'+tag+'_r'+str(repeat))
    save(run/'AD_complete.json',dict(status='complete',checkpoint=str(run/'checkpoint_AC.json'),profiling_repeats=3))
    # Only E01 characterizes transport/launch overhead; E01/E02 normal comparison
    # already uses identical CUDA-event measurements above.
    for name,extra in [('gpu',['--noDataTransfers']),('transfers',[]),('graph',['--noDataTransfers','--useCudaGraph'])]:
        directory=run/'timing'/('E01_'+name);directory.mkdir()
        command(run,[trt,'--loadEngine='+str(run/'builds/E01_baseline_perf/model.plan'),
                     '--streams=1','--warmUp=2000','--duration=60','--iterations=1000','--percentile=50,95,99',
                     '--exportTimes='+str(directory/'times.json'),input_flag]+extra,directory/'timing.log','C_trtexec_'+name)
    save(run/'collection_complete.json',dict(status='complete',nsight='not_yet_run',system='reuse_historical_evidence_then_target_unresolved_questions'))


if __name__=='__main__':
    try:
        main()
    except BaseException as exc:
        import traceback
        traceback.print_exc()
        run=Path(sys.argv[sys.argv.index('--run')+1])
        save(run/'failed_collection.json',dict(error=repr(exc),utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())))
        raise
