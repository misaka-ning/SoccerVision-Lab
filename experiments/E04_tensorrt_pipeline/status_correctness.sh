#!/usr/bin/env bash
set -euo pipefail
E04_Q_STATUS="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "$E04_Q_STATUS" <<'PY'
import json
from pathlib import Path
import sys
p=Path(sys.argv[1])
complete=p/'CORRECTNESS_COLLECTION_COMPLETE.json'
if complete.exists():
    value=json.loads(complete.read_text())
    print('正确性采集已完成：'+','.join(value['jobs'])+'；可以让 Codex 回收审查。')
    raise SystemExit(0)
history=p/'jobs.json'
jobs=json.loads(history.read_text()) if history.exists() else []
print('已通过任务：',sum(j['status']=='passed' for j in jobs))
active=[]
for d in Path('/proc').iterdir():
    if not d.name.isdigit(): continue
    try:
        args=(d/'cmdline').read_bytes().split(b'\0')
        if any(b'run_correctness_robot.py' in a for a in args[:3]) and any(str(p).encode() in a for a in args):
            active.append(d.name)
    except OSError: pass
if active:
    print('仍在运行，控制进程 PID='+','.join(active))
    if jobs: print('当前：',jobs[-1]['name'],jobs[-1]['status'])
elif jobs and jobs[-1]['status']=='failed_requires_review':
    print('已停止，需 Codex 查看日志：',jobs[-1].get('error',jobs[-1].get('returncode')))
else:
    print('当前无进程且无完成标记，请查看独立console，不要盲目重启。')
PY
