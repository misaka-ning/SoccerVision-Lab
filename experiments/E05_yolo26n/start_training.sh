#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PY=${FOOTBALL_TRAIN_PYTHON:-/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python}
RUN=$($PY -c 'import json,sys; print(json.load(open(sys.argv[1]))["run"])' "$HERE/LOCAL_READY.json")
EXTRA=()
if [[ $# -eq 1 && $1 == --resume ]]; then EXTRA=(--resume)
elif [[ $# -ne 0 ]]; then echo '用法：start_training.sh [--resume]' >&2; exit 2; fi
exec 9>"$HERE/.launch.lock"
flock -n 9 || { echo '另一个启动器正在工作，请勿重复启动。' >&2; exit 1; }
if [[ -f "$RUN/runner.pid" ]]; then
  read -r PID < "$RUN/runner.pid"
  if [[ $PID =~ ^[0-9]+$ ]] && kill -0 "$PID" 2>/dev/null && [[ -r /proc/$PID/cmdline ]] && tr '\0' ' ' < "/proc/$PID/cmdline" | grep -Fq "$HERE/e05.py train"; then
    echo "训练进程已存在 PID=$PID；请运行 status.sh。" >&2; exit 1
  fi
fi
flock -n "$HERE/.training.lock" true || { echo 'E05 训练正在运行，请勿重复启动。' >&2; exit 1; }
LOG="$RUN/train_console_$(date -u +%Y%m%dT%H%M%SZ)_$$.log"
nohup "$PY" -u "$HERE/e05.py" train --run "$RUN" "${EXTRA[@]}" > "$LOG" 2>&1 < /dev/null 9>&- &
PID=$!
printf '%s\n' "$PID" > "$RUN/runner.pid"
printf '%s\n' "$LOG" > "$RUN/latest_console.txt"
echo "已提交训练 PID=$PID；无需持续监视，请勿重复启动。"
echo "日志：$LOG"
echo "一次性查看状态：bash $HERE/status.sh"
