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
  if [[ $PID =~ ^[0-9]+$ ]] && kill -0 "$PID" 2>/dev/null && [[ -r /proc/$PID/cmdline ]] && tr '\0' ' ' < "/proc/$PID/cmdline" | grep -Fq "$HERE/e07.py train"; then
    echo "E07训练已存在 PID=$PID；请查看status.sh。" >&2; exit 1
  fi
fi
for LOCK in "$HERE/.training.lock" "$HERE/../E05_yolo26n/.training.lock"; do
  flock -n "$LOCK" true || { echo 'E05/E06/E07已有训练或冒烟任务，请勿重复启动。' >&2; exit 1; }
done
LOG="$RUN/train_console_$(date -u +%Y%m%dT%H%M%SZ)_$$.log"
nohup "$PY" -u "$HERE/e07.py" train --run "$RUN" "${EXTRA[@]}" > "$LOG" 2>&1 < /dev/null 9>&- &
PID=$!
printf '%s\n' "$PID" > "$RUN/runner.pid"
printf '%s\n' "$LOG" > "$RUN/latest_console.txt"
echo "已提交E07/WarmKD训练 PID=$PID；无需持续监视，请勿重复启动。"
echo "日志：$LOG"
echo "一次性查看状态：bash $HERE/status.sh"
