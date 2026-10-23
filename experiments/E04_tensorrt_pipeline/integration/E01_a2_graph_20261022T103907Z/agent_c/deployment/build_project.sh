#!/usr/bin/env bash
set -e
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
soccer_load_runtime no
cd "$SOCCER_PROJECT_DIR"
# Migrate once, before the first build with an external model directory.
# Subsequent builds must not compare against obsolete retained install copies.
if [[ ! -f "$SOCCER_PROJECT_DIR/install/soccer_perception_ros/share/soccer_perception_ros/source_models_directory.txt" ]]; then
  "$SOCCER_PERCEPTION_PYTHON" "$SOCCER_PROJECT_DIR/deployment/migrate_models.py" \
    --source "$SOCCER_PROJECT_DIR/install/soccer_perception_ros/share/soccer_perception_ros/models" \
    --destination "$SOCCER_MODEL_DIR"
fi
colcon build --base-paths "$SOCCER_PROJECT_DIR/soccer_perception_ros" \
  --packages-select soccer_perception_ros --event-handlers console_direct+ status- \
  --cmake-args "-DPYTHON_EXECUTABLE=$SOCCER_PERCEPTION_PYTHON"
source "$SOCCER_PROJECT_DIR/install/setup.bash"
colcon test --base-paths "$SOCCER_PROJECT_DIR/soccer_perception_ros" \
  --packages-select soccer_perception_ros --event-handlers console_direct+ status-
colcon test-result --verbose
