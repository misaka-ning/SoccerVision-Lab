# Shared Bash helpers; source this file from an entry script.
dataset_config_python() {
    if [[ -n "${FOOTBALL_DATASET_PYTHON:-}" ]]; then
        printf '%s\n' "$FOOTBALL_DATASET_PYTHON"
    elif [[ -x /opt/VisionStudio/runtime/bin/python ]]; then
        printf '%s\n' /opt/VisionStudio/runtime/bin/python
    else
        printf '%s\n' python3
    fi
}

dataset_config_field() {
    local helper_dir
    helper_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    "$(dataset_config_python)" -B "$helper_dir/dataset_config.py" --field "$1"
}
