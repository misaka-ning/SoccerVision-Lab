#!/usr/bin/env bash
set -e
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
soccer_load_runtime yes
exec ros2 launch soccer_perception_ros soccer_perception.launch.py "$@"
