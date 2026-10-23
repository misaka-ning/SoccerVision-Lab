#!/usr/bin/env bash
# Launch the confidence scan; arguments are forwarded without shell evaluation.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
scan_args=("$@")
mode=""
device=0
pending=""

for arg in "$@"; do
    if [[ "$arg" == --help || "$arg" == -h ]]; then
        cat <<'HELP'
用法：bash threshold_scan.sh [扫描参数]

不带来源参数时，提示选择已有评估缓存或模型，并输入路径。
  --eval-dir DIR    复用已有评估缓存；默认使用本机CPU环境，不加载模型
  --model FILE      先推理一次，再扫描；默认GPU 0
  --device cpu     模型模式切换为CPU
  --match-iou 0.5  固定匹配IoU
  --formats png,svg,pdf
  --output DIR     保存到新的结果目录

模型模式还支持 --dataset-version、--split、--class-id、--imgsz、--batch 等
threshold_scan.py 参数。相对路径均以仓库根目录解析。
FOOTBALL_EVAL_PYTHON 可指定Python解释器。置信度固定扫描0.05:0.01:0.95。
HELP
        exit 0
    fi
done

for arg in "$@"; do
    if [[ -n "$pending" ]]; then
        if [[ -z "$arg" || "$arg" == --* ]]; then
            printf '%s 后需要一个值。\n' "$pending" >&2
            exit 2
        fi
        if [[ "$pending" == --device ]]; then device="$arg"; fi
        pending=""
        continue
    fi
    case "$arg" in
        --model|--model=*|--eval-dir|--eval-dir=*)
            if [[ -n "$mode" ]]; then
                printf '%s\n' '--model 和 --eval-dir 只可指定其中一个来源。' >&2
                exit 2
            fi
            if [[ "$arg" == --model* ]]; then mode=model; else mode=cache; fi
            if [[ "$arg" == *=* ]]; then
                if [[ -z "${arg#*=}" ]]; then
                    printf '%s 不能为空。\n' "${arg%%=*}" >&2
                    exit 2
                fi
            else
                pending="$arg"
            fi
            ;;
        --device) pending=--device ;;
        --device=*) device="${arg#--device=}" ;;
    esac
done
if [[ -n "$pending" || -z "$device" ]]; then
    printf '%s\n' '来源路径或 --device 的值缺失。' >&2
    exit 2
fi

if [[ -z "$mode" ]]; then
    printf '%s\n' '阈值扫描：0.05 → 0.95，步长0.01，共91点。' \
        '1. 复用已有评估目录（默认，无需模型推理）' '2. 输入模型路径（先推理一次）'
    if ! read -r -p '请选择 [1/2，默认1]：' choice; then exit 1; fi
    case "${choice:-1}" in
        1) mode=cache; source_flag=--eval-dir; prompt='请输入已有评估目录：' ;;
        2) mode=model; source_flag=--model; prompt='请输入模型路径：' ;;
        *) printf '%s\n' '请选择1或2。' >&2; exit 2 ;;
    esac
    while true; do
        if ! read -r -e -p "$prompt" source_path; then
            printf '\n未输入来源路径，已退出。\n' >&2
            exit 1
        fi
        if [[ "$source_path" == \"*\" || "$source_path" == \'*\' ]]; then
            source_path="${source_path:1:${#source_path}-2}"
        fi
        if [[ -n "$source_path" ]]; then break; fi
        printf '%s\n' '路径不能为空，请重新输入。' >&2
    done
    scan_args=("$source_flag" "$source_path" "${scan_args[@]}")
fi

gpu_python="$HOME/.local/share/vision-studio/gpu-runtime/bin/python"
if [[ -n "${FOOTBALL_EVAL_PYTHON:-}" ]]; then
    python_bin="$FOOTBALL_EVAL_PYTHON"
elif [[ "$mode" == model && "$device" != cpu && -x "$gpu_python" ]]; then
    python_bin="$gpu_python"
elif [[ -x /opt/VisionStudio/runtime/bin/python ]]; then
    python_bin=/opt/VisionStudio/runtime/bin/python
else
    python_bin=python3
fi
if ! command -v -- "$python_bin" >/dev/null 2>&1; then
    printf '找不到Python：%s；可用FOOTBALL_EVAL_PYTHON指定解释器。\n' "$python_bin" >&2
    exit 1
fi

printf 'Python：%s\n扫描结果默认保存到仓库 experiments/eval/。\n' "$python_bin"
if [[ "$mode" == model ]]; then
    "$python_bin" -B "$script_dir/check_runtime.py" --device "$device"
    # Put the default before caller arguments, so explicit device options win.
    exec "$python_bin" -B "$script_dir/threshold_scan.py" --device "$device" "${scan_args[@]}"
fi
exec "$python_bin" -B "$script_dir/threshold_scan.py" "${scan_args[@]}"
