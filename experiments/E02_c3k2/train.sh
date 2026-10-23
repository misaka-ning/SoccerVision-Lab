#!/usr/bin/env bash
set -euo pipefail
experiment_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${FOOTBALL_TRAIN_PYTHON:-$HOME/.local/share/vision-studio/gpu-runtime/bin/python}"
if [[ ! -x "$python_bin" ]]; then echo "Set FOOTBALL_TRAIN_PYTHON to the E1-compatible Python runtime" >&2; exit 2; fi
export PYTHONDONTWRITEBYTECODE=1
exec "$python_bin" -B "$experiment_dir/e02.py" train "$@"
