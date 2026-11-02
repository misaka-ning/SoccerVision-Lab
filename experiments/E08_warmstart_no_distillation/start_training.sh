#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PY=${FOOTBALL_TRAIN_PYTHON:-/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python}
if [[ $# -ne 1 ]]; then echo '用法：start_training.sh <E08 run绝对路径>' >&2; exit 2; fi
exec "$PY" -u "$HERE/e08.py" train --run "$1"
