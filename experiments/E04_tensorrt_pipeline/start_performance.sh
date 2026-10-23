#!/usr/bin/env bash
set -euo pipefail
E04_P_START="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$E04_P_START/PERFORMANCE_COLLECTION_COMPLETE.json" ]]; then
  echo "本阶段性能采集已完成；保留结果，不重复启动。"
  exit 0
fi
E04_P_RESUME=0
for E04_P_ARG in "$@"; do
  case "$E04_P_ARG" in --resume) E04_P_RESUME=1 ;; esac
done
if [[ -f "$E04_P_START/performance_jobs.json" && "$E04_P_RESUME" != 1 ]]; then
  echo "已有运行记录；先查看status与失败原因，需要补测时再显式 --resume。" >&2
  exit 1
fi
E04_P_LOG="$(mktemp "$E04_P_START/console_$(date -u +%Y%m%dT%H%M%SZ)_XXXXXX.log")"
nohup bash "$E04_P_START/scripts/run_performance.sh" "$@" > "$E04_P_LOG" 2>&1 < /dev/null &
echo "已提交后台任务 PID=$!"
echo "日志：$E04_P_LOG"
echo "运行范围按本次 --scopes 参数；无需持续观察，请勿重复启动。"
echo "一次性查看状态：bash $E04_P_START/scripts/status_performance.sh"
