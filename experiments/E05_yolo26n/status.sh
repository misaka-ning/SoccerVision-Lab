#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PY=${FOOTBALL_CPU_PYTHON:-/opt/VisionStudio/runtime/bin/python}
"$PY" "$HERE/e05.py" status
RUN=$($PY -c 'import json,sys; print(json.load(open(sys.argv[1]))["run"])' "$HERE/LOCAL_READY.json")
if [[ -f "$RUN/runner.pid" ]]; then
  read -r PID < "$RUN/runner.pid"
  if [[ $PID =~ ^[0-9]+$ ]] && kill -0 "$PID" 2>/dev/null && [[ -r /proc/$PID/cmdline ]] && tr '\0' ' ' < "/proc/$PID/cmdline" | grep -Fq "$HERE/e05.py train"; then
    echo "训练进程仍存在 PID=$PID；完成与否以 status=trained 为准。"
  else
    echo '当前没有本次训练进程；若不是 trained，请检查日志。'
  fi
else
  echo '尚未通过启动器提交训练。'
fi
if [[ -f "$RUN/latest_console.txt" ]]; then
  LOG=$(cat "$RUN/latest_console.txt")
  echo "日志：$LOG"
  tail -n 8 -- "$LOG"
fi
