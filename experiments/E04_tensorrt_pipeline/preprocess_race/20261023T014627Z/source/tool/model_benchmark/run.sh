#!/usr/bin/env bash
set -e
BENCHMARK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$BENCHMARK_DIR/../../deployment/common.sh"
soccer_load_runtime yes
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export YOLO_AUTOINSTALL=false
exec "$SOCCER_PERCEPTION_PYTHON" -u "$BENCHMARK_DIR/benchmark.py" "$@"
