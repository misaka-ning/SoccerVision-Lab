#!/usr/bin/env bash
set -euo pipefail
E04_STATUS_PHASE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "$E04_STATUS_PHASE" <<'PY'
import json,sys,time
from pathlib import Path
p=Path(sys.argv[1])
if (p/'PERFORMANCE_COLLECTION_COMPLETE.json').exists():
    print('本阶段性能矩阵采集已完成，可以让 Codex 回收审查。')
    raise SystemExit(0)
active=[]
for d in Path('/proc').iterdir():
    if not d.name.isdigit(): continue
    try:
        cmd=(d/'cmdline').read_bytes()
        if b'run_performance_robot.py' in cmd and str(p).encode() in cmd: active.append(d.name)
    except OSError: pass
history=p/'performance_jobs.json'
jobs=json.loads(history.read_text()) if history.exists() else []
passed=sum(j['status']=='complete' for j in jobs)
print('已完成轮次：',passed)
if active:
    print('采集仍在运行，控制进程 PID='+','.join(active))
    running=next((j for j in reversed(jobs) if j['status']=='running'),None)
    if running:
        print('当前：',running['name'])
        raw=Path(running['output'])/'frames.csv'
        if raw.exists():
            with raw.open() as stream: count=max(0,sum(1 for _ in stream)-1)
            print('本轮已写逐帧数据：',count,'条；最后更新距今约',round(time.time()-raw.stat().st_mtime,1),'秒')
        else: print('本轮正在初始化或预热，尚未创建正式逐帧数据。')
elif jobs and jobs[-1]['status']=='failed_requires_review':
    print('任务已停止，需要 Codex 检查：',jobs[-1].get('error'))
else:
    partial=sorted(p.glob('PERFORMANCE_PARTIAL_*.json'),key=lambda x:x.stat().st_mtime)
    if partial:
        value=json.loads(partial[-1].read_text())
        print('本次阶段已完成：',','.join(value['scopes']),'；可以让 Codex 回收审查。')
    else: print('当前没有采集进程且无完成标记，请查看独立console日志，不要盲目重启。')
PY
