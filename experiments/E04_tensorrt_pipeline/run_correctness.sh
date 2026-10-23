#!/usr/bin/env bash
set -eo pipefail
E04_C_SCRIPTS="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
E04_C_PHASE="$(dirname -- "$E04_C_SCRIPTS")"
E04_C_RUN="$(dirname -- "$E04_C_PHASE")"
E04_C_PROJECT=/home/nvidia/soccer_backend_tensorrt
source "$E04_C_PROJECT/deployment/common.sh"
soccer_load_runtime yes
export PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 PYTHONIOENCODING=utf-8 YOLO_AUTOINSTALL=false
export ROS_DOMAIN_ID=87 ROS_LOCALHOST_ONLY=1
export SOCCER_MODEL_DIR="$E04_C_PROJECT/soccer_perception_ros/models"
export PYTHONPATH="$E04_C_PHASE/source/soccer_perception_ros:${PYTHONPATH:-}"
exec "$SOCCER_PERCEPTION_PYTHON" -u "$E04_C_SCRIPTS/run_correctness_robot.py" \
  --run-dir "$E04_C_RUN" --phase-dir "$E04_C_PHASE" "$@"
