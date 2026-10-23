#!/usr/bin/env bash
set -e
RACE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
/home/nvidia/miniconda3/envs/soccer_perception/bin/python - "$RACE_ROOT" <<'PY'
import json
from pathlib import Path
import sys
root=Path(sys.argv[1])
if not (root/'CURRENT').is_file():
    print('尚未启动离线筛选。');raise SystemExit()
attempt=Path((root/'CURRENT').read_text().strip())
state=json.loads((attempt/'status.json').read_text()) if (attempt/'status.json').is_file() else {}
status=state.get('status')
if status=='complete':
    if state.get('decision')=='no_correct_candidate':print('离线正确性检查已完成，无通过候选；未进入性能筛选，保留R0。')
    elif state.get('winner'):print('离线筛选已完成，候选：'+state['winner']+'；让Codex回收审查后再安排唯一一轮系统A/B。')
    else:print('离线筛选已完成，没有通过1ms及稳定性门槛的候选；按约定停止Resize/Letterbox研究，保留R0。')
elif status=='failed':print('本次失败：'+state.get('error','未知原因')+'。保留日志，请先回收审查，不要盲目重启。')
else:
    try:
        pid=int((root/'PID').read_text());args=(Path('/proc')/str(pid)/'cmdline').read_bytes()
        active=str(attempt).encode() in args and b'race.py' in args
    except (OSError,ValueError):active=False
    print(('正在执行：'+str(status or '初始化')) if active else '当前没有采集进程且未完成，请查看本次日志，不要盲目重启。')
print('日志：'+str(attempt)+'.log')
PY
