#!/usr/bin/env bash
set -eo pipefail
E04_SCRIPTS="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
E04_RUN="$(dirname -- "$E04_SCRIPTS")"
E04_PROJECT="/home/nvidia/soccer_backend_tensorrt"
source "$E04_PROJECT/deployment/common.sh"
soccer_load_runtime yes
export PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 PYTHONIOENCODING=utf-8 YOLO_AUTOINSTALL=false
export ROS_DOMAIN_ID=87 ROS_LOCALHOST_ONLY=1
exec "$SOCCER_PERCEPTION_PYTHON" -u "$E04_SCRIPTS/stage0_robot.py" \
  --project "$E04_PROJECT" --run-dir "$E04_RUN" "$@"
