#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_dir="$(CDPATH= cd -- "$project_dir/../.." && pwd)"
source "$workspace_dir/script/common/dataset_config.sh"
source_dir="$project_dir"
build_dir="$project_dir/build/release"
binary="$build_dir/football-dataset-reviewer"
lock_binary="$build_dir/qt_review_lock_runner"
qt_prefix="${QT_PREFIX:-$HOME/Qt/6.8.3/gcc_64}"
build_only=false

fail() {
    printf '数据集审核工具：%s\n' "$*" >&2
    exit 1
}

if [[ "${1:-}" == --build-only ]]; then
    build_only=true
    shift
    [[ $# -eq 0 ]] || fail '--build-only 不能与其他参数一起使用。'
fi

[[ -f "$source_dir/CMakeLists.txt" ]] || fail "未找到源码：$source_dir/CMakeLists.txt"
[[ -f "$qt_prefix/lib/cmake/Qt6/Qt6Config.cmake" && -d "$qt_prefix/plugins/platforms" ]] || \
    fail "未找到完整 Qt 6.8 SDK：$qt_prefix。请用 QT_PREFIX=/Qt/SDK/路径 指定现有 SDK。"

needs_build=false
if [[ ! -x "$binary" || ! -x "$lock_binary" || ! -f "$build_dir/.review-qt-prefix" ]]; then
    needs_build=true
elif [[ "$(cat -- "$build_dir/.review-qt-prefix")" != "$qt_prefix" ]]; then
    needs_build=true
# The prefix marker is written after every successful multi-target build.
# A CMake-only change or lock-runner rebuild need not relink the GUI binary.
elif [[ -n "$(find "$source_dir/src" "$source_dir/CMakeLists.txt" -type f -newer "$build_dir/.review-qt-prefix" -print -quit)" ]]; then
    needs_build=true
fi

if [[ "$needs_build" == true ]]; then
    command -v cmake >/dev/null 2>&1 || fail '未找到 cmake，请准备 CMake 构建环境。'
    command -v ninja >/dev/null 2>&1 || fail '未找到 ninja，请准备 Ninja 构建环境。'
    printf '正在构建数据集审核工具…\n'
    cmake -S "$source_dir" -B "$build_dir" -G Ninja \
        -U 'Qt6*_DIR' -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="$qt_prefix" -DBUILD_TESTING=OFF
    cmake --build "$build_dir" --parallel 4
    [[ -x "$binary" ]] || fail "构建结束但未找到程序：$binary"
    printf '%s\n' "$qt_prefix" > "$build_dir/.review-qt-prefix"
fi

if [[ "$build_only" == true ]]; then
    printf '程序已就绪：%s\n' "$binary"
    exit 0
fi

export LD_LIBRARY_PATH="$qt_prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export QT_PLUGIN_PATH="$qt_prefix/plugins${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}"
export QT_QPA_PLATFORM_PLUGIN_PATH="$qt_prefix/plugins/platforms${QT_QPA_PLATFORM_PLUGIN_PATH:+:$QT_QPA_PLATFORM_PLUGIN_PATH}"

has_dataset=false
skip_value=false
for arg in "$@"; do
    if [[ "$skip_value" == true ]]; then skip_value=false; continue; fi
    case "$arg" in
        --dataset|--dataset=*|-d|-d?*|--help|-h) has_dataset=true ;;
        --image-list|--smoke|--gallery-page) skip_value=true ;;
        -*) ;;
        *) has_dataset=true ;;
    esac
done
if [[ "$has_dataset" == false ]]; then
    dataset_root="$(dataset_config_field root)"
    printf '共享配置数据集：%s\n' "$dataset_root"
    set -- --dataset "$dataset_root" "$@"
fi

exec "$binary" "$@"
