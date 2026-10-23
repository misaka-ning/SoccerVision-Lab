#!/usr/bin/env bash
set -eo pipefail
E04_P_SCRIPTS="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
E04_P_PHASE="$(dirname -- "$E04_P_SCRIPTS")"
E04_P_RUN="$(dirname -- "$E04_P_PHASE")"
E04_P_PROJECT=/home/nvidia/soccer_backend_tensorrt
source "$E04_P_PROJECT/deployment/common.sh"
soccer_load_runtime yes
export PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 PYTHONIOENCODING=utf-8 YOLO_AUTOINSTALL=false
export ROS_DOMAIN_ID=87 ROS_LOCALHOST_ONLY=1
export SOCCER_MODEL_DIR="$E04_P_PROJECT/soccer_perception_ros/models"
# Select the source phase named by this immutable performance manifest.
E04_P_SOURCE_PHASE="$("$SOCCER_PERCEPTION_PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["correctness_phase"])' "$E04_P_PHASE/performance_manifest.json")"
export PYTHONPATH="$E04_P_RUN/$E04_P_SOURCE_PHASE/source/soccer_perception_ros:${PYTHONPATH:-}"
exec "$SOCCER_PERCEPTION_PYTHON" -u "$E04_P_SCRIPTS/run_performance_robot.py" \
  --run-dir "$E04_P_RUN" --phase-dir "$E04_P_PHASE" "$@"
