#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PY=${FOOTBALL_CPU_PYTHON:-/opt/VisionStudio/runtime/bin/python}
if [[ $# -ne 1 ]]; then echo '用法：status.sh <E08 run绝对路径>' >&2; exit 2; fi
exec "$PY" "$HERE/e08.py" status --run "$1"
