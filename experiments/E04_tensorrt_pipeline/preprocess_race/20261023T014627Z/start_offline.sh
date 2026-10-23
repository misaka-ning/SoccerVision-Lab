#!/usr/bin/env bash
set -e
RACE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source /home/nvidia/soccer_backend_tensorrt/deployment/common.sh
soccer_load_runtime yes
export ROS_DOMAIN_ID=87 ROS_LOCALHOST_ONLY=1
exec 9>"$SOCCER_PROJECT_DIR/results/.preprocess_race_gpu.lock"
if ! flock -n 9; then
  echo '已有本轮离线采集在运行；没有重复启动。'
  exit 1
fi
exec 8>"$SOCCER_PROJECT_DIR/results/E04_tensorrt_pipeline/20261022T020842Z_78f1b7/gpu_benchmark.lock"
if ! flock -n 8; then
  echo '旧 E04 benchmark 正在运行；未启动本轮。'
  exit 1
fi
if [[ -f "$RACE_ROOT/CURRENT" ]]; then
  previous="$(cat "$RACE_ROOT/CURRENT")"
  if [[ -f "$previous/status.json" ]] && "$SOCCER_PERCEPTION_PYTHON" -c 'import json,sys; sys.exit(json.load(open(sys.argv[1])).get("status")!="complete")' "$previous/status.json"; then
    echo '本轮已完成，请先回收结果，不重复采集。'
    exit 0
  fi
fi
attempt="$RACE_ROOT/offline_$(date -u +%Y%m%dT%H%M%SZ)_$RANDOM"
printf '%s\n' "$attempt" > "$RACE_ROOT/CURRENT"
nohup "$SOCCER_PERCEPTION_PYTHON" -B -u "$RACE_ROOT/tools/race.py" \
  --out "$attempt" --iterations 400 > "$attempt.log" 2>&1 < /dev/null &
pid=$!
printf '%s\n' "$pid" > "$RACE_ROOT/PID"
echo "已启动离线筛选 PID=$pid"
echo "日志：$attempt.log"
echo "只读既有61对Val，不开相机、不发布ROS、不修改生产配置。无需持续监视，请勿重复启动。"
echo "完成后查看：bash $RACE_ROOT/status_offline.sh"
