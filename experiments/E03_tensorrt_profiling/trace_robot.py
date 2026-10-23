#!/usr/bin/env python3
"""Short, explicitly bounded resident-input trace after excluded warmup."""
import argparse
import json
from pathlib import Path
import sys
import time


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--engine',type=Path,required=True)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--iterations',type=int,default=60)
    p.add_argument('--warmup',type=int,default=100)
    p.add_argument('--graph',action='store_true')
    a=p.parse_args()
    assert a.iterations>=5 and a.warmup>=1 and not a.output.exists()
    sys.path.insert(0,'/home/nvidia/soccer_backend_tensorrt/tool/model_benchmark')
    from worker import Engine
    import numpy as np
    import torch
    engine=Engine(a.engine,'auto');engine.allocate(42)
    inp=next(i for i,v in enumerate(engine.io) if v['input'])
    value=np.fromfile(str(a.input),dtype=np.float32).reshape(2,3,640,640)
    engine.tensors[inp].copy_(torch.from_numpy(value).to('cuda:0'))
    torch.cuda.synchronize()
    for _ in range(a.warmup):engine.execute()
    torch.cuda.synchronize()
    execute=engine.execute;graph_error=None
    if a.graph:
        output_index=next(i for i,v in enumerate(engine.io) if not v['input'])
        reference=engine.tensors[output_index].detach().cpu().numpy().copy()
        graph=torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph,stream=engine.stream):
            assert engine.context.execute_async_v2(engine.addresses,engine.stream.cuda_stream)
        def graph_execute():
            begin=time.perf_counter()
            with torch.cuda.stream(engine.stream):
                engine.start.record(engine.stream);graph.replay();engine.end.record(engine.stream)
            engine.end.synchronize()
            return engine.start.elapsed_time(engine.end),(time.perf_counter()-begin)*1000
        execute=graph_execute
        for _ in range(5):execute()
        result=engine.tensors[output_index].detach().cpu().numpy().copy()
        graph_error=float(np.max(np.abs(reference-result)))
        assert np.array_equal(reference,result),'Graph output differs on the fixed representative batch'
    records=[]
    torch.cuda.profiler.start()
    # Initialize graph-node activity collection before the measured NVTX ROI.
    # The first graph launch after collection starts can have partial node data.
    if a.graph:
        for _ in range(3):execute()
    torch.cuda.nvtx.range_push('E03_steady_window')
    for i in range(a.iterations):
        torch.cuda.nvtx.range_push('E03_iteration_%04d' % i)
        start=time.monotonic_ns();gpu,wall=execute();end=time.monotonic_ns()
        torch.cuda.nvtx.range_pop()
        records.append(dict(iteration=i,monotonic_start_ns=start,monotonic_end_ns=end,
                            instrumented_gpu_ms=gpu,instrumented_execute_wall_ms=wall))
    torch.cuda.nvtx.range_pop()
    torch.cuda.synchronize()
    torch.cuda.profiler.stop()
    a.output.write_text(json.dumps(dict(engine=engine.info,warmup_excluded=a.warmup,iterations=a.iterations,
                                        cuda_graph=a.graph,graph_output_max_abs_error=graph_error,
                                        active_profiler_priming_excluded=3 if a.graph else 0,
                                        capture='explicit cudaProfilerStart/Stop and per-iteration NVTX',
                                        scope='resident input, single synchronous execute; trace timings are instrumented, not deployment results',records=records),indent=2)+'\n')


if __name__=='__main__':main()
