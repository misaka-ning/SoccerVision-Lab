#!/usr/bin/env bash
# Sourced by deployment helpers; keep ROS setup scripts compatible with nounset.
SOCCER_PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

soccer_load_ros() {
  local distro="${SOCCER_ROS_DISTRO:-foxy}"
  local setup="/opt/ros/$distro/setup.bash"
  if [[ ! -f "$setup" ]]; then
    echo "Missing ROS2 setup: $setup. See docs/deployment_jetson.md." >&2
    return 1
  fi
  # Preserve ROS_DOMAIN_ID and transport settings used by robot networking.
  # Drop inherited Noetic or stale ROS2 overlays for this standalone project.
  unset ROS_DISTRO ROS_VERSION ROS_PYTHON_VERSION ROS_PACKAGE_PATH ROS_ROOT ROS_ETC_DIR
  unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH PYTHONPATH
  export AMENT_TRACE_SETUP_FILES="${AMENT_TRACE_SETUP_FILES-}"
  source "$setup"
}

soccer_load_runtime() {
  local with_install="${1:-yes}"
  local env_file="$SOCCER_PROJECT_DIR/.soccer_perception_env"
  if [[ ! -f "$env_file" ]]; then
    echo 'Run bash deployment/setup_dependencies.sh --yes first.' >&2
    return 1
  fi
  # ROS and ZED must take precedence over libraries inherited from policy Conda.
  export LD_LIBRARY_PATH=""
  soccer_load_ros
  source "$env_file"
  export SOCCER_MODEL_DIR="${SOCCER_MODEL_DIR:-$SOCCER_PROJECT_DIR/soccer_perception_ros/models}"
  # Jetson CUDA torch wheels may live in the user site directory.
  unset PYTHONNOUSERSITE
  if [[ ! -x "${SOCCER_PERCEPTION_PYTHON:-}" ]]; then
    echo 'Project Python is missing. Re-run deployment/setup_dependencies.sh on this robot.' >&2
    return 1
  fi
  if [[ "$with_install" == yes ]]; then
    if [[ ! -f "$SOCCER_PROJECT_DIR/install/setup.bash" ]]; then
      echo 'Run bash deployment/build_project.sh first.' >&2
      return 1
    fi
    source "$SOCCER_PROJECT_DIR/install/setup.bash"
  fi
}
