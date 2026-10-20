#!/usr/bin/env bash
# Open an immutable batch or 50-image group against the canonical dataset.
set -euo pipefail
script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_dir="$(CDPATH= cd -- "$script_dir/../.." && pwd)"
source "$workspace_dir/script/common/dataset_config.sh"
usage() {
    printf '用法：%s <1-9> [--priority | --group <正整数|next> | --groups] [审核工具其他参数]\n' "$0" >&2
    printf '例如：%s 1 --group 1\n      %s 1 --groups\n' "$0" "$0" >&2
}
fail() { printf '%s\n' "$*" >&2; exit 2; }
if [[ $# -lt 1 || ! "$1" =~ ^[1-9]$ ]]; then
    usage
    exit 2
fi
batch_number="$1"
shift
selection="batch"
group_number=""
reviewer_args=()
group_start_page=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --priority|--groups)
            [[ "$selection" == batch ]] || fail '不能重复或同时使用 --priority、--group、--groups。'
            selection="${1#--}"
            shift
            ;;
        --group)
            [[ "$selection" == batch ]] || fail '不能重复或同时使用 --priority、--group、--groups。'
            [[ $# -ge 2 ]] || fail '--group 后需要正整数或 next。'
            group_number="$2"
            [[ "$group_number" == next || "$group_number" =~ ^[1-9][0-9]*$ ]] || fail '--group 后需要正整数或 next。'
            selection="group"
            shift 2
            ;;
        --dataset|--dataset=*|--image-list|--image-list=*)
            fail '本脚本使用共享配置选定的数据版本和对应批次名单，不能传入 --dataset 或 --image-list。'
            ;;
        *)
            reviewer_args+=("$1")
            shift
            ;;
    esac
done
printf -v batch_name 'batch-%03d.txt' "$batch_number"
dataset_root="$(dataset_config_field root)"
records_root="$(dataset_config_field review_records)"
list_path="$records_root/batches/$batch_name"
helper_path="$script_dir/review_football_groups.py"
if [[ "$selection" == groups ]]; then
    [[ ${#reviewer_args[@]} -eq 0 ]] || fail '--groups 仅显示进度，不能附加审核工具参数。'
    [[ -f "$helper_path" ]] || fail "找不到分组工具：$helper_path"
    exec "$(dataset_config_python)" -B "$helper_path" status --batch "$batch_number"
elif [[ "$selection" == priority ]]; then
    list_path="${list_path%.txt}-priority.txt"
elif [[ "$selection" == group ]]; then
    if [[ "$group_number" == next ]]; then
        [[ -f "$helper_path" ]] || fail "找不到分组工具：$helper_path"
        group_number="$("$(dataset_config_python)" -B "$helper_path" next --batch "$batch_number")"
        if [[ -z "$group_number" ]]; then
            printf '第 %s 批的全部固定分组均已完成审核。\n' "$batch_number"
            exit 0
        fi
        [[ "$group_number" =~ ^[1-9][0-9]*$ ]] || fail '分组工具返回了无效的组号。'
    fi
    [[ ${#group_number} -le 3 ]] || fail "找不到第 $group_number 组。"
    printf -v group_name 'group-%03d.txt' "$group_number"
    list_path="${list_path%.txt}-remaining-50/$group_name"
    [[ -s "$list_path" ]] || fail "找不到第 $group_number 组：$list_path"
    [[ -f "$helper_path" ]] || fail "找不到分组工具：$helper_path"
    # Load the entire fixed sequence, then open the requested 50-image page.
    # A single group's list would disable the next-page button after 50 images.
    list_path="$("$(dataset_config_python)" -B "$helper_path" gallery-list --batch "$batch_number")"
    group_start_page="$group_number"
fi
[[ -s "$list_path" ]] || { printf '找不到批次名单：%s\n' "$list_path" >&2; exit 2; }
if [[ "$selection" == group ]]; then
    printf '打开第 %s 批、第 %s 组；固定名单不随审核进度重新分组。\n' "$batch_number" "$group_number"
else
    printf '打开第 %s 批；保存到 %s。通过审核由你手动确认。\n' "$batch_number" "$dataset_root"
fi
if [[ "$selection" == group ]]; then
    has_gallery=false
    for arg in "${reviewer_args[@]}"; do
        [[ "$arg" != --gallery ]] || has_gallery=true
        case "$arg" in
            --gallery-page|--gallery-page=*) fail '分组起始页由 --group 指定，请勿重复传入 --gallery-page。' ;;
        esac
    done
    [[ "$has_gallery" == true ]] || reviewer_args+=(--gallery)
    reviewer_args+=(--gallery-page "$group_start_page")
fi
exec "$script_dir/review_dataset.sh" --dataset "$dataset_root" --image-list "$list_path" "${reviewer_args[@]}"
