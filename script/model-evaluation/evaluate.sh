#!/usr/bin/env bash
# Interactive launcher; extra arguments are forwarded to evaluate.py.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
device=0
dry_run=false
expects_device=false
for arg in "$@"; do
    if [[ "$expects_device" == true ]]; then
        device="$arg"
        expects_device=false
        continue
    fi
    case "$arg" in
        --device) expects_device=true ;;
        --device=*) device="${arg#--device=}" ;;
        --dry-run) dry_run=true ;;
    esac
done
if [[ "$expects_device" == true || -z "$device" || "$device" == --* ]]; then
    printf '%s\n' '--device 后需要设备编号（如0）或cpu。' >&2
    exit 2
fi
gpu_python="$HOME/.local/share/vision-studio/gpu-runtime/bin/python"
if [[ -n "${FOOTBALL_EVAL_PYTHON:-}" ]]; then
    python_bin="$FOOTBALL_EVAL_PYTHON"
elif [[ "$device" != cpu && -x "$gpu_python" ]]; then
    python_bin="$gpu_python"
elif [[ -x /opt/VisionStudio/runtime/bin/python ]]; then
    python_bin=/opt/VisionStudio/runtime/bin/python
else
    python_bin=python3
fi
if ! command -v -- "$python_bin" >/dev/null 2>&1; then
    printf '找不到Python环境：%s\n可用FOOTBALL_EVAL_PYTHON指定已安装评估依赖的Python。\n' "$python_bin" >&2
    exit 1
fi

for arg in "$@"; do
    if [[ "$arg" == --help || "$arg" == -h ]]; then
        printf '用法：bash %s [评估参数]\n启动后输入模型路径；默认Val、GPU 0，优先使用本机CUDA环境。\n用--device cpu切换CPU，可用FOOTBALL_EVAL_PYTHON指定Python环境。\n相对模型路径以当前终端目录解析，支持~/和包含空格的路径。\n\n' "${BASH_SOURCE[0]}"
        exec "$python_bin" -B "$script_dir/evaluate.py" --help
    fi
    if [[ "$arg" == --model || "$arg" == --model=* ]]; then
        printf '请在启动后的提示中输入模型路径；其他参数可直接追加。\n' >&2
        exit 2
    fi
done

printf '足球检测模型评估（默认Val / device=%s）\nPython：%s\n' "$device" "$python_bin"
if [[ "$dry_run" == false ]]; then
    # Check before asking for a model or scanning the dataset/creating results.
    "$python_bin" -B "$script_dir/check_runtime.py" --device "$device"
fi
while true; do
    if ! read -r -e -p '请输入模型路径（.pt/.onnx/.engine/.torchscript）：' model_path; then
        printf '\n未输入模型路径，已退出。\n' >&2
        exit 1
    fi
    # Accept matching outer quotes pasted from a terminal; never evaluate input.
    if [[ "$model_path" == \"*\" || "$model_path" == \'*\' ]]; then
        model_path="${model_path:1:${#model_path}-2}"
    fi
    case "$model_path" in
        '~/'*) model_path="$HOME/${model_path:2}" ;;
    esac
    if [[ -z "$model_path" ]]; then
        printf '模型路径不能为空，请重新输入。\n' >&2
        continue
    fi
    if [[ "$model_path" != /* ]]; then
        model_path="$PWD/$model_path"
    fi
    if [[ ! -f "$model_path" ]]; then
        printf '文件不存在：%s\n请重新输入。\n' "$model_path" >&2
        continue
    fi
    break
done

printf 'Python：%s\n模型：%s\n结果默认保存到仓库的 experiments/eval/，完成后会显示具体目录。\n' "$python_bin" "$model_path"
exec "$python_bin" -B "$script_dir/evaluate.py" --model "$model_path" --device "$device" "$@"
