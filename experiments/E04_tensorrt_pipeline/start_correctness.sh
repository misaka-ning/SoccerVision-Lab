#!/usr/bin/env bash
set -euo pipefail
E04_START_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$E04_START_DIR/CORRECTNESS_COLLECTION_COMPLETE.json" ]]; then
  echo "正确性采集已完成；保留结果，不重复启动。"
  exit 0
fi
if [[ -f "$E04_START_DIR/jobs.json" && "${1:-}" != --resume ]]; then
  echo "已有运行记录；请查看日志，确认退出和失败原因后再显式 --resume。" >&2
  exit 1
fi
E04_START_LOG="$(mktemp "$E04_START_DIR/console_$(date -u +%Y%m%dT%H%M%SZ)_XXXXXX.log")"
nohup bash "$E04_START_DIR/scripts/run_correctness.sh" "$@" > "$E04_START_LOG" 2>&1 < /dev/null &
E04_START_PID=$!
echo "已提交后台任务 PID=$E04_START_PID"
echo "日志：$E04_START_LOG"
echo "无需持续观察；请勿重复启动。"
