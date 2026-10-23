#!/usr/bin/env python3
"""CPU-only E03 layer attribution, raw latency distributions and trace analysis."""
import argparse
from bisect import bisect_right
from collections import defaultdict
import csv
import json
from pathlib import Path
import re
import sqlite3

import numpy as np


# Frozen E01/E02 top-level architecture; indexes match models_list YAML.
MODULE_TYPES=['Conv','Conv','C3k2','Conv','C3k2','Conv','C3k2','Conv','C3k2','SPPF','C2PSA',
              'Upsample','Concat','C3k2','Upsample','Concat','C3k2','Conv','Concat','C3k2','Conv','Concat','C3k2','Detect']
PSA22_PREFIX='/model.22/m.0/m.0.1/'


def attention_block(layer,ids):
    if ids==[10]:return 'L10_C2PSA'
    if ids!=[22]:return ''
    info=layer.get('Name','')+' '+str(layer.get('Metadata',''))
    paths=re.findall(r'/model\.22/[A-Za-z0-9_./]+',info)
    inside=[v for v in paths if v.startswith(PSA22_PREFIX)]
    outside=[v for v in paths if not v.startswith(PSA22_PREFIX)]
    return 'L22_PSA_boundary_fusion' if inside and outside else 'L22_PSA' if inside else ''


def auxiliary_kind(layer_type,name):
    # Friendly-name labels remain comparable when legacy metadata has no types.
    if 'reformat' in name.lower():return 'Reformat'
    if re.search(r'\bcopy(?:node)?\b',name,re.I) or layer_type=='Copy':return 'Copy'
    if layer_type=='Reformat':return 'Reformat'
    if layer_type=='Cast':return 'Cast_or_other'
    return ''

def write_json(path,value):
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')


def write_csv(path,rows):
    if not rows:return
    with Path(path).open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,list(rows[0]));writer.writeheader();writer.writerows(rows)


def stats(values):
    a=np.asarray(values,dtype=float)
    return dict(n=len(a),mean=float(a.mean()),p50=float(np.percentile(a,50)),
                p95=float(np.percentile(a,95)),p99=float(np.percentile(a,99)),
                min=float(a.min()),max=float(a.max())) if len(a) else {}


def attribute(layer):
    name=layer.get('Name','')
    info=name+' '+str(layer.get('Metadata',''))
    ids=sorted(set(map(int,re.findall(r'model[./](\d+)(?:[/.\s\]]|$)',info))))
    typ=layer.get('LayerType','')
    block=attention_block(layer,ids)
    if auxiliary_kind(typ,name):
        group='Auxiliary'
    elif len(ids)>1:group='Cross-module fusion'
    elif block=='L22_PSA_boundary_fusion':group='Cross-submodule fusion'
    elif block=='L22_PSA':group='Attention'
    elif len(ids)==1:
        i=ids[0]
        group='Backbone (excl Attention)' if i<10 else 'Attention' if i==10 else 'Neck (excl embedded PSA)' if i<23 else 'Detect' if i==23 else 'Unattributed'
    else:group='Unattributed'
    return ids,group


def profiles(run,out,folder='profiles',prefix=''):
    all_results={}
    for tag in ['E01_baseline','E02_c3k2']:
        paths=sorted((run/folder).glob(tag+'_r*/profile.json'))
        if not paths:continue
        layers={}
        for p in paths:
            info=json.loads((p.parent/'layers.json').read_text())
            items=info.get('Layers',[]) if isinstance(info,dict) else info
            for layer in items:
                if isinstance(layer,str):layer=dict(Name=layer,LayerType='unavailable (layer_names_only)')
                layers[layer['Name']]=layer
        times=defaultdict(list)
        for p in paths:
            for row in json.loads(p.read_text()):
                if 'name' in row:times[row['name']].append(float(row['averageMs']))
        rows=[]
        for name,values in times.items():
            layer=layers.get(name,dict(Name=name,LayerType='metadata unavailable'))
            ids,group=attribute(layer)
            def tensors(key):
                return json.dumps([{k:v for k,v in t.items() if k in ['Name','Dimensions','Format/Datatype','Format','DataType']} for t in layer.get(key,[])],ensure_ascii=False)
            rows.append(dict(name=name,group=group,modules=','.join(map(str,ids)),layer_type=layer.get('LayerType'),
                             yolo_modules='; '.join('%d:%s'%(i,MODULE_TYPES[i] if i<len(MODULE_TYPES) else 'unknown') for i in ids),
                             attention_block=attention_block(layer,ids),
                             auxiliary_kind=auxiliary_kind(layer.get('LayerType',''),name),
                             mean_ms=float(np.mean(values)),repeat_min_ms=min(values),repeat_max_ms=max(values),repeats=len(values),
                             inputs=tensors('Inputs'),outputs=tensors('Outputs'),
                             tactic=layer.get('TacticName',layer.get('TacticValue',layer.get('Implementation','unavailable'))),
                             metadata_available=name in layers,l19_associated=19 in ids))
        rows.sort(key=lambda r:r['mean_ms'],reverse=True)
        total=sum(r['mean_ms'] for r in rows)
        groups=defaultdict(float);l19=0.;l19_cross=0.
        for rank,row in enumerate(rows,1):
            row['rank']=rank;row['percent_of_profile']=row['mean_ms']/total*100 if total else 0.
            groups[row['group']]+=row['mean_ms']
            if row['l19_associated']:
                if row['modules']=='19':l19+=row['mean_ms']
                else:l19_cross+=row['mean_ms']
        summary=dict(profile_repeats=len(paths),layer_count=len(rows),sum_average_ms=total,
                     modules={k:dict(ms=v,percent=v/total*100) for k,v in groups.items()},
                     auxiliary_breakdown_ms={kind:sum(r['mean_ms'] for r in rows if r['group']=='Auxiliary' and r['auxiliary_kind']==kind) for kind in ['Reformat','Copy','Cast_or_other']},
                     attention_named_matmul_softmax_ms=sum(r['mean_ms'] for r in rows if r['group']=='Attention' and re.search('MatMul|Softmax',r['name'])),
                     attention_named_matmul_softmax_layers=sum(r['group']=='Attention' and bool(re.search('MatMul|Softmax',r['name'])) for r in rows),
                     attention_definition='Whole top-level C2PSA L10 plus identifiable embedded PSA subblock /model.22/m.0/m.0.1/; remove the latter from Neck; auxiliary and boundary fusion separate',
                     attention_blocks={block:dict(core_ms=sum(r['mean_ms'] for r in rows if r['attention_block']==block and r['group']=='Attention'),
                                                  auxiliary_ms=sum(r['mean_ms'] for r in rows if r['attention_block']==block and r['group']=='Auxiliary')) for block in ['L10_C2PSA','L22_PSA']},
                     structural_core_ms={label:sum(r['mean_ms'] for r in rows if r['modules'] and ',' not in r['modules'] and lo<=int(r['modules'])<=hi and r['group'] not in ['Auxiliary','Cross-module fusion']) for label,lo,hi in [('Backbone_incl_C2PSA',0,10),('Neck_incl_embedded_PSA',11,22),('Detect',23,23)]},
                     l19_exclusive_ms=l19,l19_cross_module_associated_ms=l19_cross,
                     l19_core_ms=sum(r['mean_ms'] for r in rows if r['modules']=='19' and r['group']!='Auxiliary'),
                     l19_auxiliary_ms=sum(r['mean_ms'] for r in rows if r['modules']=='19' and r['group']=='Auxiliary'),
                     metadata_coverage_count=sum(r['metadata_available'] for r in rows),
                     io_shape_coverage_count=sum(bool(json.loads(r['inputs'])) and bool(json.loads(r['outputs'])) for r in rows),
                     tactic_coverage_count=sum(r['tactic'] not in (None,'unavailable','') for r in rows),
                     profile_scope=('frozen legacy Engine' if folder=='profiles_legacy' else 'detailed newly-built Engine')+'; real representative resident batch2 input; profiler timings, not production latency')
        all_results[tag]=summary
        write_csv(out/(prefix+tag+'_layers.csv'),rows);write_csv(out/(prefix+tag+'_top20.csv'),rows[:20])
        write_csv(out/(prefix+tag+'_L19.csv'),[r for r in rows if r['l19_associated']])
        lines=['| Rank | YOLO modules | Type | ms/batch | % profile | Layer |','|---:|---|---|---:|---:|---|']
        for row in rows[:20]:lines.append('| %d | %s | %s | %.5f | %.2f | `%s` |' % (row['rank'],row['modules'] or row['group'],row['layer_type'],row['mean_ms'],row['percent_of_profile'],row['name'].replace('|','/')))
        (out/(prefix+tag+'_TOP20.md')).write_text('\n'.join(lines)+'\n')
    write_json(out/(prefix+'profile_summary.json'),all_results)
    return all_results


def latency(run,out):
    rows=[]
    for folder in ['legacy_benchmark','standard_benchmark','profile_benchmark']:
        grouped=defaultdict(list)
        for path in sorted((run/folder).glob('*/**/frames.csv')):
            result=path.parent/'controller_result.json'
            if not result.exists():continue
            meta=json.loads(result.read_text())
            if meta.get('status')!='complete' or meta.get('mode')!='engine':continue
            values=list(csv.DictReader(path.open()))
            for field in ['engine_ms','execute_wall_ms']:
                a=[float(r[field]) for r in values]
                entry=dict(group=folder,model=meta['model'],round=meta['round'],metric=field,**stats(a))
                rows.append(entry);grouped[(meta['model'],field)].extend(a)
        for (model,field),values in grouped.items():rows.append(dict(group=folder,model=model,round='pooled',metric=field,**stats(values)))
    write_csv(out/'normal_timings.csv',rows);write_json(out/'normal_timings.json',rows)
    return rows


def trtexec_timings(run,out):
    result=[]
    for path in sorted((run/'timing').glob('*/times.json')):
        data=json.loads(path.read_text())
        if not data:continue
        row=dict(case=path.parent.name,samples=len(data),units='ms/batch; trtexec one-batch-ahead submission')
        for field in ['computeMs','h2dMs','d2hMs','latencyMs']:
            row[field]=stats([v[field] for v in data])
        row['enqueueMs']=stats([v['endEnqMs']-v['startEnqMs'] for v in data])
        log=path.with_name('timing.log').read_text(errors='replace')
        row['reported_log_mean_ms']={}
        for label in ['Enqueue Time','GPU Compute Time','H2D Latency','D2H Latency']:
            match=re.search(r'\[I\] '+re.escape(label)+r':[^\n]*?\bmean = ([0-9.eE+-]+) ms',log)
            if match:row['reported_log_mean_ms'][label]=float(match.group(1))
        row['enqueue_precision_note']='Exported absolute start/end timestamps are rounded; report uses the directly logged Enqueue Time mean, retaining recomputation separately.'
        row['cuda_graph_configured_enabled']='CUDA Graph: Enabled' in log
        match=re.search(r'Throughput:\s*([0-9.]+)\s*qps',log)
        row['throughput_batches_per_s']=float(match.group(1)) if match else None
        row['graph_log_lines']=[v for v in log.splitlines() if 'graph' in v.lower() and any(t in v.lower() for t in ['captur','fail','success','using'])]
        result.append(row)
    write_json(out/'trtexec_timings.json',result)
    return result


def union(intervals):
    merged=[]
    for start,end in sorted((int(start),int(end)) for start,end in intervals):
        if end<=start:continue
        if merged and start<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],end)
        else:merged.append([int(start),int(end)])
    return merged


def overlap_ns(first,second):
    """Intersection length of two sorted disjoint interval lists."""
    i=j=0;total=0
    while i<len(first) and j<len(second):
        a,b=first[i];c,d=second[j]
        total+=max(0,min(b,d)-max(a,c))
        if b<=d:i+=1
        else:j+=1
    return total


def trace(path,out):
    db=sqlite3.connect(str(path));db.row_factory=sqlite3.Row
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    schema={t:[r[1] for r in db.execute('PRAGMA table_info("%s")' % t)] for t in tables}
    strings=dict(db.execute('SELECT id,value FROM StringIds')) if 'StringIds' in tables else {}
    kernels=[dict(r) for r in db.execute('SELECT * FROM CUPTI_ACTIVITY_KIND_KERNEL')] if 'CUPTI_ACTIVITY_KIND_KERNEL' in tables else []
    nvtx=[dict(r) for r in db.execute('SELECT * FROM NVTX_EVENTS')] if 'NVTX_EVENTS' in tables else []
    for row in nvtx:row['label']=row.get('text') or strings.get(row.get('textId'),'')
    iterations=[r for r in nvtx if r['label'].startswith('E03_iteration_') and r.get('end') is not None and r['end']>r['start']]
    windows=[r for r in nvtx if r['label']=='E03_steady_window' and r.get('end') is not None and r['end']>r['start']]
    if not kernels or not iterations or not windows:
        result=dict(trace_smoke_pass=False,kernels=len(kernels),complete_iterations=len(iterations),steady_windows=len(windows),schema=schema)
        write_json(out/(path.stem+'_analysis.json'),result);db.close();return result
    lo,hi=windows[0]['start'],windows[0]['end']
    kernels=[r for r in kernels if r['start']>=lo and r['end']<=hi]
    def intervals(rows):return [(max(lo,r['start']),min(hi,r['end'])) for r in rows if r['end']>lo and r['start']<hi]
    busy=union(intervals(kernels));copies=[]
    for table in ['CUPTI_ACTIVITY_KIND_MEMCPY','CUPTI_ACTIVITY_KIND_MEMSET']:
        if table in tables:copies.extend(dict(r) for r in db.execute('SELECT * FROM '+table))
    all_busy=union(busy+intervals(copies))
    gaps=[];pos=lo
    for start,end in all_busy:
        if start>pos:gaps.append((pos,start))
        pos=max(pos,end)
    if pos<hi:gaps.append((pos,hi))
    api=[]
    for table,domain in [('CUPTI_ACTIVITY_KIND_RUNTIME','runtime'),('CUPTI_ACTIVITY_KIND_DRIVER','driver')]:
        if table in tables:
            for row in db.execute('SELECT * FROM '+table):
                item=dict(row);item['api_domain']=domain;api.append(item)
    api=[r for r in api if lo<=r['start'] and r['end']<=hi]
    api_groups=defaultdict(list)
    for row in api:
        api_groups[(row['api_domain'],strings.get(row.get('nameId'),str(row.get('nameId'))))].append((row['end']-row['start'])/1e6)
    api_rows=[dict(api_domain=domain,name=name,total_ms=sum(v),**stats(v)) for (domain,name),v in api_groups.items()]
    api_rows.sort(key=lambda r:r['total_ms'],reverse=True)
    kernel_groups=defaultdict(list)
    for row in kernels:
        name=strings.get(row.get('demangledName'),strings.get(row.get('shortName'),'unknown'))
        kernel_groups[name].append((row['end']-row['start'])/1e6)
    kernel_rows=[dict(name=name,total_ms=sum(v),**stats(v)) for name,v in kernel_groups.items()]
    kernel_rows.sort(key=lambda r:r['total_ms'],reverse=True)
    iteration_rows=[]
    for row in iterations:
        a,b=row['start'],row['end'];selected=[r for r in kernels if a<=r['start'] and r['end']<=b]
        merged=union([(r['start'],r['end']) for r in selected])
        work=sum(y-x for x,y in merged)
        iteration_rows.append(dict(iteration=row['label'],wall_ms=(b-a)/1e6,kernel_busy_ms=work/1e6,kernels=len(selected),non_kernel_wall_ms=(b-a-work)/1e6))
    api_union=union([(r['start'],r['end']) for r in api])
    phases={};all_phase_intervals=[]
    for label in sorted({v['label'] for v in nvtx if v['label'].startswith('detector_')}):
        ranges=[(max(lo,v['start']),min(hi,v['end'])) for v in nvtx if v['label']==label and v.get('end') is not None and v['end']>lo and v['start']<hi]
        merged=union(ranges);all_phase_intervals.extend(merged)
        wall=sum(b-a for a,b in merged);gpu=overlap_ns(merged,all_busy)
        phases[label]=dict(calls=len(ranges),wall_ms_per_batch=wall/1e6/len(iterations),
                           gpu_activity_ms_per_batch=gpu/1e6/len(iterations),
                           no_gpu_activity_ms_per_batch=(wall-gpu)/1e6/len(iterations),
                           cpu_api_wall_overlap_ms_per_batch=overlap_ns(merged,api_union)/1e6/len(iterations))
    merged_phases=union(all_phase_intervals)
    if merged_phases:
        phase_wall=sum(b-a for a,b in merged_phases);phase_gpu=overlap_ns(merged_phases,all_busy)
        outside_gpu=sum(b-a for a,b in all_busy)-phase_gpu
        outside_wall=hi-lo-phase_wall
        phases['framework_or_outside_method_ranges']=dict(wall_ms_per_batch=outside_wall/1e6/len(iterations),gpu_activity_ms_per_batch=outside_gpu/1e6/len(iterations),no_gpu_activity_ms_per_batch=(outside_wall-outside_gpu)/1e6/len(iterations))
    gap_rows=[]
    detector_ranges=[v for v in nvtx if v['label'].startswith('detector_') and v.get('end') is not None]
    api_ends=[v[1] for v in api_union]
    for a,b in gaps:
        labels=sorted({v['label'] for v in detector_ranges if v['start']<b and v['end']>a})
        index=bisect_right(api_ends,a);api_overlap=0
        while index<len(api_union) and api_union[index][0]<b:
            x,y=api_union[index];api_overlap+=max(0,min(b,y)-max(a,x));index+=1
        gap_rows.append(dict(start_offset_ms=(a-lo)/1e6,end_offset_ms=(b-lo)/1e6,duration_ms=(b-a)/1e6,
                             overlapping_detector_ranges='; '.join(labels),
                             cpu_api_wall_overlap_ms=api_overlap/1e6))
    write_csv(out/(path.stem+'_gaps.csv'),gap_rows)
    consistent=len(set(r['kernels'] for r in iteration_rows))==1
    result=dict(trace_smoke_pass=len(iterations)>=5 and len(kernels)>0 and all(r['kernels']>0 for r in iteration_rows) and consistent,window_ms=(hi-lo)/1e6,
                constant_replay_kernel_count_consistent=consistent,
                complete_iterations=len(iterations),kernels=len(kernels),kernel_busy_union_ms=sum(b-a for a,b in busy)/1e6,
                kernel_count_per_iteration=stats([r['kernels'] for r in iteration_rows]),
                runtime_api_events=sum(r['api_domain']=='runtime' for r in api),driver_api_events=sum(r['api_domain']=='driver' for r in api),
                cpu_api_wall_union_ms=sum(b-a for a,b in api_union)/1e6,
                graph_launch_calls_by_domain={domain:sum(v['n'] for v in api_rows if v['api_domain']==domain and 'GraphLaunch' in v['name']) for domain in ['runtime','driver']},
                api_time_note='Runtime and driver APIs may nest and may overlap GPU execution; totals are API wall time, not CPU core busy time.',
                gpu_activity_union_ms=sum(b-a for a,b in all_busy)/1e6,
                copy_or_memset_incremental_ms=(sum(b-a for a,b in all_busy)-sum(b-a for a,b in busy))/1e6,
                detector_phase_overlap=phases,
                application_no_gpu_activity_ms=sum(b-a for a,b in gaps)/1e6,
                application_no_gpu_activity_gaps=stats([(b-a)/1e6 for a,b in gaps]),
                top10_application_no_gpu_activity_gaps_ms=sorted([(b-a)/1e6 for a,b in gaps],reverse=True)[:10],
                per_iteration_kernel_busy_ms=stats([r['kernel_busy_ms'] for r in iteration_rows]),
                per_iteration_wall_ms=stats([r['wall_ms'] for r in iteration_rows]),
                coverage='target application only; other GPU processes and CPU scheduling not established; instrumented trace, not normal timing',schema=schema)
    write_json(out/(path.stem+'_analysis.json'),result)
    write_csv(out/(path.stem+'_api.csv'),api_rows);write_csv(out/(path.stem+'_kernels.csv'),kernel_rows)
    write_csv(out/(path.stem+'_iterations.csv'),iteration_rows)
    db.close()
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    out=a.run/'analysis';out.mkdir(exist_ok=True)
    result=dict(profiles=profiles(a.run,out),legacy_profiles=profiles(a.run,out,'profiles_legacy','LEGACY_'),timing_rows=len(latency(a.run,out)),trtexec=trtexec_timings(a.run,out))
    for path in (a.run/'trace').glob('*.sqlite'):result[path.stem]=trace(path,out)
    write_json(out/'analysis_status.json',result)
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
