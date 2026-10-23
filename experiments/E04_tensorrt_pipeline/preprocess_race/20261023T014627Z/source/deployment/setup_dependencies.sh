#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGINAL_ARGS=("$@")
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MODEL_DIR="${SOCCER_MODEL_DIR:-$ROOT/soccer_perception_ros/models}"

CONDA_BIN="${CONDA_BIN:-}"
CONDA_ENV_NAME="${SOCCER_CONDA_ENV:-soccer_perception}"
CONDA_PYTHON_VERSION="${SOCCER_CONDA_PYTHON_VERSION:-3.8}"
ENV_FILE="$ROOT/.soccer_perception_env"
PYTHON_BIN=""
USE_CONDA=1
ROS_DISTRO="${ROS_DISTRO_OVERRIDE:-foxy}"
TORCH_FLAVOR="${TORCH_FLAVOR:-auto}"
YES=0
CHECK_ONLY=0
WITH_ROS=1
WITH_VISER=0
WITH_TENSORRT_PIP="${WITH_TENSORRT_PIP:-auto}"
ARCH="$(uname -m)"
IS_AARCH64=0
if [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
  IS_AARCH64=1
fi

source "$SCRIPT_DIR/dependencies.sh"
VISER_VERSION=""
if [[ "$VISER_SPEC" == viser==* ]]; then
  VISER_VERSION="${VISER_SPEC#viser==}"
fi
NUMPY_VERSION="${NUMPY_SPEC#numpy==}"
PROTOBUF_VERSION="${PROTOBUF_SPEC#protobuf==}"
ONNX_VERSION="${ONNX_SPEC#onnx==}"
ONNXSLIM_VERSION="${ONNXSLIM_SPEC#onnxslim==}"

usage() {
  cat <<'USAGE'
Usage: bash deployment/setup_dependencies.sh [options]

Create or reuse a conda environment, scan this soccer perception project
runtime, and install missing dependencies into that environment.

Options:
  --yes                 Install without interactive confirmation.
  --check-only          Only scan. Do not create envs or install packages.
  --conda PATH          Path to conda executable.
  --env-name NAME       Conda env name to create/reuse. Default: soccer_perception.
  --python-version VER  Python version for new envs. Default: 3.8.
  --python PATH         Use an existing Python instead of creating a conda env.
  --no-ros              Skip ROS2 apt package checks.
  --ros-distro NAME     ROS2 distro for apt packages. Default: foxy.
  --with-viser          Install/check optional Viser web viewer package.
  --no-viser            Skip Viser web viewer package (default).
  --with-tensorrt-pip   Try pip install for TensorRT Python bindings.
  --no-tensorrt-pip     Do not try pip install for TensorRT Python bindings.
  --torch-flavor NAME   Torch wheel flavor: auto, cu121, cpu, or jetson. Default: auto.
  -h, --help            Show this help.

Environment:
  SOCCER_CONDA_ENV=soccer_perception
  SOCCER_CONDA_PYTHON_VERSION=3.8
  CONDA_BIN=/path/to/conda
  TORCH_FLAVOR=auto|cu121|cpu|jetson
  PROTOBUF_SPEC='protobuf==3.20.3'
  ONNX_SPEC='onnx==1.17.0'
  ONNXSLIM_SPEC='onnxslim==0.1.94'
  TENSORRT_SPEC='tensorrt==11.1.0.106'
  VISER_SPEC='viser==1.0.30'

Notes:
  - ZED SDK must already be installed under /usr/local/zed.
  - If /usr/local/zed/get_python_api.py exists, this script will use it to
    install pyzed.sl into the conda env.
  - On Jetson/aarch64, the script accepts NVIDIA-provided torch wheels such as
    2.0.0+nv23.5 instead of forcing the x86_64 2.4.1+cu121 baseline.
  - TensorRT export from .pt requires ONNX and a protobuf version new enough
    for ONNX generated bindings. These are installed into the conda env even
    when Jetson runtime packages are available from system paths.
  - ROS2 rclpy is loaded through /opt/ros/<distro>/setup.bash, not pip.
USAGE
}

log() {
  printf '[setup] %s\n' "$*"
}

warn() {
  printf '[setup][warn] %s\n' "$*" >&2
}

die() {
  printf '[setup][error] %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y)
      YES=1
      shift
      ;;
    --check-only)
      CHECK_ONLY=1
      shift
      ;;
    --conda)
      [[ $# -ge 2 ]] || die "--conda requires a path"
      CONDA_BIN="$2"
      shift 2
      ;;
    --env-name)
      [[ $# -ge 2 ]] || die "--env-name requires a name"
      CONDA_ENV_NAME="$2"
      shift 2
      ;;
    --python-version)
      [[ $# -ge 2 ]] || die "--python-version requires a version"
      CONDA_PYTHON_VERSION="$2"
      shift 2
      ;;
    --python)
      [[ $# -ge 2 ]] || die "--python requires a path"
      PYTHON_BIN="$2"
      USE_CONDA=0
      shift 2
      ;;
    --no-ros)
      WITH_ROS=0
      shift
      ;;
    --ros-distro)
      [[ $# -ge 2 ]] || die "--ros-distro requires a name"
      ROS_DISTRO="$2"
      shift 2
      ;;
    --with-viser)
      WITH_VISER=1
      shift
      ;;
    --no-viser)
      WITH_VISER=0
      shift
      ;;
    --with-tensorrt-pip)
      WITH_TENSORRT_PIP="yes"
      shift
      ;;
    --no-tensorrt-pip)
      WITH_TENSORRT_PIP="no"
      shift
      ;;
    --torch-flavor)
      [[ $# -ge 2 ]] || die "--torch-flavor requires auto, cu121, cpu, or jetson"
      TORCH_FLAVOR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

export LD_LIBRARY_PATH="/usr/local/zed/lib:${LD_LIBRARY_PATH:-}"
export PYTHONNOUSERSITE=1

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=()
else
  SUDO=(sudo)
fi

confirm() {
  local prompt="$1"
  if [[ "$YES" -eq 1 ]]; then
    return 0
  fi
  read -r -p "$prompt [y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" || "$answer" == "yes" || "$answer" == "YES" ]]
}

find_conda() {
  if [[ -n "$CONDA_BIN" ]]; then
    [[ -x "$CONDA_BIN" ]] || die "conda is not executable: $CONDA_BIN"
    return 0
  fi

  local candidate
  for candidate in \
    "$(command -v conda || true)" \
    "$HOME/miniconda3/bin/conda" \
    "$HOME/anaconda3/bin/conda" \
    "/opt/conda/bin/conda"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      CONDA_BIN="$candidate"
      return 0
    fi
  done
  return 1
}

conda_env_exists() {
  "$CONDA_BIN" env list | awk '{print $1}' | grep -Fxq "$CONDA_ENV_NAME"
}

conda_env_python() {
  "$CONDA_BIN" run -n "$CONDA_ENV_NAME" python -c 'import sys; print(sys.executable)'
}

create_conda_env() {
  local -a args=(create -y -n "$CONDA_ENV_NAME")
  if [[ "$IS_AARCH64" -eq 1 ]]; then
    args+=(-c conda-forge --override-channels)
  fi
  args+=("python=${CONDA_PYTHON_VERSION}" pip)
  "$CONDA_BIN" "${args[@]}"
}

ensure_runtime_python() {
  if [[ "$USE_CONDA" -eq 0 ]]; then
    [[ -n "$PYTHON_BIN" && -x "$PYTHON_BIN" ]] || die "Python is not executable: $PYTHON_BIN"
    return 0
  fi

  find_conda || die "conda was not found; install Miniconda/Anaconda or pass --conda PATH"
  log "Conda: $CONDA_BIN"
  if conda_env_exists; then
    log "Reusing conda env: $CONDA_ENV_NAME"
  else
    if [[ "$CHECK_ONLY" -eq 1 ]]; then
      warn "Conda env '$CONDA_ENV_NAME' does not exist. Run without --check-only to create it."
      PYTHON_BIN=""
      return 0
    fi
    confirm "Create conda env '$CONDA_ENV_NAME' with Python $CONDA_PYTHON_VERSION?" || die "conda env creation was declined"
    log "Creating conda env '$CONDA_ENV_NAME'"
    create_conda_env
  fi

  PYTHON_BIN="$(conda_env_python)"
  [[ -n "$PYTHON_BIN" && -x "$PYTHON_BIN" ]] || die "failed to resolve Python for conda env '$CONDA_ENV_NAME'"
}

ensure_jetson_system_site_path() {
  [[ "$IS_AARCH64" -eq 1 ]] || return 0
  [[ "$USE_CONDA" -eq 1 ]] || return 0
  [[ -n "$PYTHON_BIN" ]] || return 0
  [[ "$CHECK_ONLY" -eq 0 ]] || return 0

  local site_dir
  site_dir="$("$PYTHON_BIN" - <<'PY'
import site
paths = site.getsitepackages()
print(paths[0] if paths else "")
PY
)"
  [[ -n "$site_dir" && -d "$site_dir" ]] || return 0

  local pth="$site_dir/jetson-runtime-packages.pth"
  # Jetson vendor packages such as torch, torchvision, pyzed, and tensorrt are
  # often installed outside the conda env. Keep these paths as late fallbacks.
  # Pure Python project/export dependencies are still forced into the conda env
  # by check_python_spec so stale system/user protobuf or onnx cannot win.
  local -a candidates=(
    "/usr/lib/python3.8/dist-packages"
    "/usr/lib/python3/dist-packages"
    "/usr/local/lib/python3.8/dist-packages"
    "/usr/local/lib/python3/dist-packages"
  )
  local -a existing=()
  local path
  for path in "${candidates[@]}"; do
    [[ -d "$path" ]] && existing+=("$path")
  done
  [[ "${#existing[@]}" -gt 0 ]] || return 0

  log "Adding Jetson runtime Python package paths to conda env: $pth"
  printf '%s\n' "${existing[@]}" > "$pth"
}

remove_jetson_system_site_path() {
  [[ "$IS_AARCH64" -eq 1 ]] || return 0
  [[ "$USE_CONDA" -eq 1 ]] || return 0
  [[ -n "$PYTHON_BIN" ]] || return 0
  [[ "$CHECK_ONLY" -eq 0 ]] || return 0

  local site_dir
  site_dir="$("$PYTHON_BIN" - <<'PY'
import site
paths = site.getsitepackages()
print(paths[0] if paths else "")
PY
)"
  [[ -n "$site_dir" && -d "$site_dir" ]] || return 0

  local pth="$site_dir/jetson-runtime-packages.pth"
  if [[ -f "$pth" ]]; then
    log "Temporarily removing Jetson runtime Python package paths: $pth"
    rm -f "$pth"
  fi
}

write_runtime_env_file() {
  [[ -n "$PYTHON_BIN" ]] || return 0
  [[ "$CHECK_ONLY" -eq 0 ]] || return 0

  log "Writing runtime env file: $ENV_FILE"
  {
    printf '# Generated by setup_dependencies.sh. Source this file before ros2 launch.\n'
    printf 'export SOCCER_PERCEPTION_PYTHON=%q\n' "$PYTHON_BIN"
    printf 'export SOCCER_CONDA_ENV=%q\n' "$CONDA_ENV_NAME"
    printf 'export PYTHONNOUSERSITE=1\n'
    printf '%s\n' 'export LD_LIBRARY_PATH="/usr/local/zed/lib:${LD_LIBRARY_PATH:-}"'
  } > "$ENV_FILE"
}

python_version_ok() {
  "$PYTHON_BIN" - "$REQUIRED_PYTHON_VERSION" "$IS_AARCH64" <<'PY'
import sys
required = tuple(int(x) for x in sys.argv[1].split("."))
is_aarch64 = sys.argv[2] == "1"
current = sys.version_info[:2]
print(f"{sys.executable}: Python {sys.version.split()[0]}")
if is_aarch64 and current != required:
    print(
        "Jetson ROS Foxy/TensorRT/ZED Python packages are tied to "
        f"Python {sys.argv[1]}; do not reuse a Python {current[0]}.{current[1]} conda env.",
        file=sys.stderr,
    )
    raise SystemExit(1)
raise SystemExit(0 if current >= required else 1)
PY
}

check_python_spec() {
  local import_name="$1"
  local dist_name="$2"
  local required_version="$3"

  "$PYTHON_BIN" - "$import_name" "$dist_name" "$required_version" <<'PY'
import importlib
import importlib.metadata as metadata
from pathlib import Path
import sys

import_name, dist_name, required_version = sys.argv[1:4]
try:
    module = importlib.import_module(import_name)
except Exception as exc:
    print(f"MISSING {import_name}: {exc}")
    raise SystemExit(2)

prefix = Path(sys.prefix).resolve()
module_file = getattr(module, "__file__", None)
if module_file:
    resolved_module = Path(module_file).resolve()
    if prefix not in (resolved_module, *resolved_module.parents):
        print(f"LOCATION_MISMATCH {import_name}: loaded_from={resolved_module} expected_prefix={prefix}")
        raise SystemExit(5)

if required_version:
    try:
        dist = metadata.distribution(dist_name)
        installed = dist.version
    except Exception as exc:
        print(f"VERSION_UNKNOWN {dist_name}: {exc}")
        raise SystemExit(3)
    dist_root = Path(dist.locate_file("")).resolve()
    if prefix not in (dist_root, *dist_root.parents):
        print(f"LOCATION_MISMATCH {dist_name}: dist_root={dist_root} expected_prefix={prefix}")
        raise SystemExit(5)
    public_installed = installed.split("+", 1)[0]
    if public_installed != required_version:
        print(f"VERSION_MISMATCH {dist_name}: installed={installed} required={required_version}")
        raise SystemExit(4)
    # Some wheels expose a module version that intentionally omits wheel build
    # suffixes, e.g. opencv-python 4.12.0.88 imports as cv2.__version__ 4.12.0.
    module_version = "" if import_name == "cv2" else getattr(module, "__version__", "")
    if module_version:
        public_module_version = str(module_version).split("+", 1)[0]
        if public_module_version != required_version:
            print(
                f"VERSION_MISMATCH {import_name}: "
                f"imported={module_version} required={required_version} dist={installed}"
            )
            raise SystemExit(4)
    print(f"OK {dist_name}=={installed}")
else:
    version = getattr(module, "__version__", "")
    suffix = f" {version}" if version else ""
    print(f"OK {import_name}{suffix}")
PY
}

check_import_only() {
  local code="$1"
  local label="$2"
  "$PYTHON_BIN" - "$code" "$label" <<'PY'
import sys
code, label = sys.argv[1:3]
try:
    exec(code, {})
except Exception as exc:
    print(f"MISSING {label}: {exc}")
    raise SystemExit(1)
print(f"OK {label}")
PY
}

ensure_pip() {
  if "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    return 0
  fi
  log "pip is missing for $PYTHON_BIN"
  [[ "$CHECK_ONLY" -eq 0 ]] || return 1
  "$PYTHON_BIN" -m ensurepip --upgrade
}

pip_install() {
  local -a args=("$@")
  [[ "${#args[@]}" -gt 0 ]] || return 0
  [[ "$CHECK_ONLY" -eq 0 ]] || return 0
  ensure_pip
  log "Installing Python packages: ${args[*]}"
  "$PYTHON_BIN" -m pip install "${args[@]}"
}

pip_install_ignore_installed() {
  local -a args=("$@")
  [[ "${#args[@]}" -gt 0 ]] || return 0
  [[ "$CHECK_ONLY" -eq 0 ]] || return 0
  ensure_pip
  log "Installing Python packages without touching system packages: ${args[*]}"
  "$PYTHON_BIN" -m pip install --ignore-installed "${args[@]}"
}

pip_install_no_deps() {
  local -a args=("$@")
  [[ "${#args[@]}" -gt 0 ]] || return 0
  [[ "$CHECK_ONLY" -eq 0 ]] || return 0
  ensure_pip
  log "Installing Python packages without dependency resolution: ${args[*]}"
  "$PYTHON_BIN" -m pip install --no-deps "${args[@]}"
}

pip_install_viser() {
  [[ "$WITH_VISER" -eq 1 ]] || return 0
  [[ "$CHECK_ONLY" -eq 0 ]] || return 0
  ensure_pip
  if [[ "$IS_AARCH64" -eq 1 ]]; then
    log "Installing Viser into the conda env with Jetson-safe NumPy: $VISER_SPEC $NUMPY_SPEC"
    "$PYTHON_BIN" -m pip install --ignore-installed "$VISER_SPEC" "$NUMPY_SPEC"
    "$PYTHON_BIN" -m pip install --force-reinstall --no-deps "$NUMPY_SPEC" "$PROTOBUF_SPEC"
  else
    log "Installing Viser into the runtime Python env: $VISER_SPEC"
    "$PYTHON_BIN" -m pip install --ignore-installed "$VISER_SPEC"
  fi
}

pip_install_base() {
  local -a args=("$@")
  [[ "${#args[@]}" -gt 0 ]] || return 0
  [[ "$CHECK_ONLY" -eq 0 ]] || return 0
  ensure_pip
  log "Installing base Python packages into the conda env: ${args[*]}"
  "$PYTHON_BIN" -m pip install --upgrade --force-reinstall "${args[@]}"
}

pip_install_torch() {
  local -a specs=("$@")
  [[ "${#specs[@]}" -gt 0 ]] || return 0
  [[ "$CHECK_ONLY" -eq 0 ]] || return 0
  ensure_pip
  local index_url
  local flavor="$TORCH_FLAVOR"
  if [[ "$flavor" == "auto" ]]; then
    if [[ "$IS_AARCH64" -eq 1 ]]; then
      flavor="jetson"
    else
      flavor="cu121"
    fi
  fi
  case "$flavor" in
    jetson)
      warn "Jetson/aarch64 PyTorch should come from NVIDIA JetPack wheels or an NVIDIA container; skipping generic pip install: ${specs[*]}"
      return 0
      ;;
    cu121)
      index_url="https://download.pytorch.org/whl/cu121"
      ;;
    cpu)
      index_url="https://download.pytorch.org/whl/cpu"
      ;;
    *)
      die "unsupported --torch-flavor: $TORCH_FLAVOR"
      ;;
  esac
  log "Installing PyTorch packages from $index_url: ${specs[*]}"
  "$PYTHON_BIN" -m pip install --index-url "$index_url" "${specs[@]}"
}

find_jetson_torch_wheel() {
  local wheel
  for wheel in \
    "$ROOT"/.deps/torch*.whl \
    "$ROOT"/deps/torch*.whl \
    "$ROOT"/wheels/torch*.whl \
    "$HOME"/Downloads/torch*.whl \
    "$HOME"/Downloads/torch+torchvision+zedsdk/torch*.whl; do
    if [[ -f "$wheel" ]]; then
      printf '%s\n' "$wheel"
      return 0
    fi
  done
  return 1
}

find_jetson_torchvision_wheel() {
  local wheel
  for wheel in \
    "$ROOT"/.deps/torchvision*.whl \
    "$ROOT"/deps/torchvision*.whl \
    "$ROOT"/wheels/torchvision*.whl \
    "$HOME"/Downloads/torchvision*.whl \
    "$HOME"/Downloads/torch+torchvision+zedsdk/torchvision*.whl; do
    if [[ -f "$wheel" ]]; then
      printf '%s\n' "$wheel"
      return 0
    fi
  done
  return 1
}

find_jetson_torchvision_source() {
  local dir
  for dir in \
    "$ROOT"/.deps/vision \
    "$ROOT"/.deps/vision-* \
    "$ROOT"/deps/vision \
    "$ROOT"/deps/vision-* \
    "$HOME"/Downloads/torch+torchvision+zedsdk/vision-0.15.0-rc8 \
    "$HOME"/Downloads/torch+torchvision+zedsdk/vision; do
    if [[ -f "$dir/setup.py" || -f "$dir/pyproject.toml" ]]; then
      printf '%s\n' "$dir"
      return 0
    fi
  done
  return 1
}

install_jetson_torch_runtime() {
  [[ "$IS_AARCH64" -eq 1 ]] || return 0
  [[ -n "$PYTHON_BIN" ]] || return 0
  [[ "$CHECK_ONLY" -eq 0 ]] || return 0
  ensure_pip
  remove_jetson_system_site_path

  if ! check_python_any_version "torch" "torch"; then
    local torch_wheel
    if torch_wheel="$(find_jetson_torch_wheel)"; then
      log "Installing Jetson PyTorch wheel: $torch_wheel"
      "$PYTHON_BIN" -m pip install --no-cache-dir "$torch_wheel"
    else
      warn "No local Jetson torch wheel found. Expected torch*.whl under $ROOT/.deps, $ROOT/wheels, or $HOME/Downloads."
    fi
  fi

  if ! check_python_any_version "torchvision" "torchvision"; then
    local torchvision_wheel torchvision_source
    if torchvision_wheel="$(find_jetson_torchvision_wheel)"; then
      log "Installing Jetson torchvision wheel: $torchvision_wheel"
      "$PYTHON_BIN" -m pip install --no-cache-dir "$torchvision_wheel"
    elif torchvision_source="$(find_jetson_torchvision_source)"; then
      log "Building and installing Jetson torchvision from source: $torchvision_source"
      (cd "$torchvision_source" && "$PYTHON_BIN" -m pip install --no-cache-dir --no-build-isolation .)
    else
      warn "No local Jetson torchvision wheel/source found. Expected torchvision*.whl or vision source under $ROOT/.deps, $ROOT/wheels, or $HOME/Downloads/torch+torchvision+zedsdk."
    fi
  fi

  "$PYTHON_BIN" -m pip install --force-reinstall --no-deps "$NUMPY_SPEC" "$PROTOBUF_SPEC"
  ensure_jetson_system_site_path
}

install_zed_python_api() {
  local helper="/usr/local/zed/get_python_api.py"
  [[ -f "$helper" ]] || return 1
  [[ "$CHECK_ONLY" -eq 0 ]] || return 0

  ensure_pip
  remove_jetson_system_site_path
  pip_install "$REQUESTS_SPEC"
  "$PYTHON_BIN" -m pip install --upgrade --ignore-installed "cython>=3.0.0"
  mkdir -p "$ROOT/.deps/zed_python"
  log "Installing pyzed.sl with $helper"
  if ! "$PYTHON_BIN" "$helper" --path "$ROOT/.deps/zed_python"; then
    ensure_jetson_system_site_path
    return 1
  fi
  "$PYTHON_BIN" -m pip install --force-reinstall --no-deps "$NUMPY_SPEC" "$PROTOBUF_SPEC"
  ensure_jetson_system_site_path
}

apt_package_installed() {
  dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed'
}

install_apt_packages() {
  local -a packages=("$@")
  [[ "${#packages[@]}" -gt 0 ]] || return 0
  [[ "$CHECK_ONLY" -eq 0 ]] || return 0
  command -v apt-get >/dev/null 2>&1 || die "apt-get not found; cannot install ROS/system packages"
  confirm "Install apt packages: ${packages[*]}?" || return 0
  log "Running apt-get update"
  "${SUDO[@]}" apt-get update
  log "Installing apt packages: ${packages[*]}"
  "${SUDO[@]}" apt-get install -y "${packages[@]}"
}

ros_clean_env_prefix() {
  env \
    -u ROS_DISTRO \
    -u ROS_VERSION \
    -u ROS_PYTHON_VERSION \
    -u ROS_PACKAGE_PATH \
    -u ROS_ROOT \
    -u ROS_ETC_DIR \
    -u ROS_MASTER_URI \
    -u ROS_IP \
    -u ROSLISP_PACKAGE_DIRECTORIES \
    -u AMENT_PREFIX_PATH \
    -u COLCON_PREFIX_PATH \
    "$@"
}

check_ros_python() {
  local setup="/opt/ros/${ROS_DISTRO}/setup.bash"
  [[ -n "$PYTHON_BIN" && -f "$setup" ]] || return 1
  ros_clean_env_prefix bash -lc "source '$setup' && '$PYTHON_BIN' -c 'import rclpy; import geometry_msgs.msg; import std_msgs.msg'"
}

check_python_any_version() {
  local import_name="$1"
  local dist_name="$2"

  "$PYTHON_BIN" - "$import_name" "$dist_name" <<'PY'
import importlib
import importlib.metadata as metadata
import sys

import_name, dist_name = sys.argv[1:3]
try:
    importlib.import_module(import_name)
except Exception as exc:
    print(f"MISSING {import_name}: {exc}")
    raise SystemExit(1)
try:
    version = metadata.version(dist_name)
except Exception:
    version = "unknown"
print(f"OK {dist_name}=={version}")
PY
}

should_try_tensorrt_pip() {
  if [[ "$WITH_TENSORRT_PIP" == "yes" ]]; then
    return 0
  fi
  if [[ "$WITH_TENSORRT_PIP" == "no" ]]; then
    return 1
  fi
  [[ "$IS_AARCH64" -eq 0 ]]
}

log "Project root: $ROOT"
ensure_runtime_python
remove_jetson_system_site_path

missing_pip=()
missing_base_pip=()
missing_torch=()
missing_viser=0
missing_manual=()
missing_apt=()
need_pyzed_install=0
pyzed_can_auto_install=0
need_rescan_after_base_install=0
base_pip_specs=("$NUMPY_SPEC" "$OPENCV_SPEC" "$PYYAML_SPEC" "$PROTOBUF_SPEC" "$ONNX_SPEC" "$ONNXSLIM_SPEC")

if [[ -z "$PYTHON_BIN" ]]; then
  missing_manual+=("Conda env '$CONDA_ENV_NAME' is missing; run: bash deployment/setup_dependencies.sh --yes")
else
  log "Runtime Python: $PYTHON_BIN"
  python_version_ok || die "Python >= $REQUIRED_PYTHON_VERSION is required"

  scan_python_pkg() {
    local import_name="$1"
    local dist_name="$2"
    local required_version="$3"
    local pip_spec="$4"
    local group="$5"

    if check_python_spec "$import_name" "$dist_name" "$required_version"; then
      return 0
    fi
    if [[ "$group" == "base" ]]; then
      missing_base_pip+=("$pip_spec")
      need_rescan_after_base_install=1
    elif [[ "$group" == "torch" ]]; then
      missing_torch+=("$pip_spec")
    else
      missing_pip+=("$pip_spec")
    fi
  }

  scan_python_pkg "numpy" "numpy" "$NUMPY_VERSION" "$NUMPY_SPEC" "base"
  scan_python_pkg "cv2" "opencv-python" "${OPENCV_SPEC#*==}" "$OPENCV_SPEC" "base"
  scan_python_pkg "yaml" "PyYAML" "${PYYAML_SPEC#*==}" "$PYYAML_SPEC" "base"
  scan_python_pkg "google.protobuf" "protobuf" "$PROTOBUF_VERSION" "$PROTOBUF_SPEC" "base"
  scan_python_pkg "onnx" "onnx" "$ONNX_VERSION" "$ONNX_SPEC" "base"
  scan_python_pkg "onnxslim" "onnxslim" "$ONNXSLIM_VERSION" "$ONNXSLIM_SPEC" "base"

  if [[ "$need_rescan_after_base_install" -eq 0 ]]; then
    if [[ "$IS_AARCH64" -eq 1 && "$CHECK_ONLY" -eq 0 ]]; then
      install_jetson_torch_runtime
    fi
    ensure_jetson_system_site_path

    if [[ "$IS_AARCH64" -eq 1 ]]; then
      if ! check_python_any_version "torch" "torch"; then
        missing_manual+=("PyTorch for Jetson/aarch64: install NVIDIA JetPack-compatible torch wheel or use an NVIDIA PyTorch container")
      fi
      if ! check_python_any_version "torchvision" "torchvision"; then
        missing_manual+=("torchvision for Jetson/aarch64: install the version matched to the NVIDIA JetPack torch wheel")
      fi
    else
      scan_python_pkg "torch" "torch" "${TORCH_SPEC#*==}" "$TORCH_SPEC" "torch"
      scan_python_pkg "torchvision" "torchvision" "${TORCHVISION_SPEC#*==}" "$TORCHVISION_SPEC" "torch"
    fi
    scan_python_pkg "ultralytics" "ultralytics" "${ULTRALYTICS_SPEC#*==}" "$ULTRALYTICS_SPEC" "pip"

    if [[ "$WITH_VISER" -eq 1 ]]; then
      if ! check_python_spec "viser" "viser" "$VISER_VERSION" ; then
        missing_viser=1
      fi
    fi

    if ! check_import_only "import pyzed.sl" "pyzed.sl"; then
      need_pyzed_install=1
      if [[ -f /usr/local/zed/get_python_api.py ]]; then
        pyzed_can_auto_install=1
      else
        missing_manual+=("ZED SDK Python API: /usr/local/zed/get_python_api.py not found")
      fi
    fi

    if ! check_import_only "import tensorrt" "tensorrt"; then
      if should_try_tensorrt_pip; then
        missing_pip+=("--extra-index-url")
        missing_pip+=("https://pypi.nvidia.com")
        missing_pip+=("$TENSORRT_SPEC")
      else
        missing_manual+=("TensorRT Python bindings: install matching NVIDIA JetPack/TensorRT Python package, or rerun with --with-tensorrt-pip")
      fi
    fi
  else
    warn "Skipping Jetson runtime package checks until base packages are installed in the conda env."
  fi
fi

if [[ ! -d /usr/local/zed/lib ]]; then
  missing_manual+=("ZED runtime library directory /usr/local/zed/lib")
else
  log "OK /usr/local/zed/lib"
fi

if [[ ! -f "$MODEL_DIR/yolo26s.pt" ]]; then
  missing_manual+=("Model file $MODEL_DIR/yolo26s.pt")
else
  log "OK model $MODEL_DIR/yolo26s.pt"
fi

if [[ ! -f "$MODEL_DIR/yolo26s.engine" ]]; then
  warn "No source-tree engine at $MODEL_DIR/yolo26s.engine; run bash deployment/build_engine.sh explicitly before starting TensorRT inference"
else
  log "OK engine $MODEL_DIR/yolo26s.engine"
fi

if [[ "$WITH_ROS" -eq 1 ]]; then
  ros_setup="/opt/ros/${ROS_DISTRO}/setup.bash"
  if [[ ! -f "$ros_setup" ]]; then
    missing_manual+=("ROS2 ${ROS_DISTRO}: install ROS2 first so $ros_setup exists")
  else
    log "OK ROS setup $ros_setup"
    ros_packages=(
      "ros-${ROS_DISTRO}-ament-cmake-python"
      "ros-${ROS_DISTRO}-ament-cmake-test"
      "ros-${ROS_DISTRO}-ament-index-python"
      "ros-${ROS_DISTRO}-rclpy"
      "ros-${ROS_DISTRO}-std-msgs"
      "ros-${ROS_DISTRO}-geometry-msgs"
      "ros-${ROS_DISTRO}-launch"
      "ros-${ROS_DISTRO}-launch-ros"
      "ros-${ROS_DISTRO}-rmw-cyclonedds-cpp"
      "python3-colcon-common-extensions"
    )
    for package in "${ros_packages[@]}"; do
      if apt_package_installed "$package"; then
        log "OK apt $package"
      else
        missing_apt+=("$package")
      fi
    done
    if [[ -z "$PYTHON_BIN" ]]; then
      warn "Skipping ROS Python import check until conda env '$CONDA_ENV_NAME' exists"
    elif check_ros_python; then
      log "OK ROS Python imports through $ros_setup"
    else
      missing_manual+=("ROS Python import path: source $ros_setup before ROS runs, or install missing ROS Python packages")
    fi
  fi
fi

echo
log "Scan summary"
printf '  Base Python packages: %s\n' "${missing_base_pip[*]:-(none)}"
printf '  Python pip packages: %s\n' "${missing_pip[*]:-(none)}"
if [[ "$WITH_VISER" -eq 1 ]]; then
  if [[ -z "$PYTHON_BIN" ]]; then
    printf '  Viser web viewer: not checked because runtime conda env is missing\n'
  elif [[ "$missing_viser" -eq 1 ]]; then
    printf '  Viser web viewer: %s\n' "$VISER_SPEC"
  else
    printf '  Viser web viewer: ok\n'
  fi
else
  printf '  Viser web viewer: skipped\n'
fi
printf '  PyTorch packages: %s\n' "${missing_torch[*]:-(none)}"
if [[ -z "$PYTHON_BIN" ]]; then
  printf '  ZED Python API: not checked because runtime conda env is missing\n'
elif [[ "$need_pyzed_install" -eq 1 && "$pyzed_can_auto_install" -eq 1 ]]; then
  printf '  ZED Python API: will install with /usr/local/zed/get_python_api.py\n'
else
  printf '  ZED Python API: %s\n' "$( [[ "$need_pyzed_install" -eq 1 ]] && printf 'missing' || printf 'ok' )"
fi
printf '  apt packages: %s\n' "${missing_apt[*]:-(none)}"
if [[ "${#missing_manual[@]}" -eq 0 ]]; then
  printf '  manual/system items: (none)\n'
else
  printf '  manual/system items:\n'
  for item in "${missing_manual[@]}"; do
    printf '    - %s\n' "$item"
  done
fi

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  log "Check-only mode; no envs or packages were installed."
  exit 0
fi

if [[ "${#missing_base_pip[@]}" -gt 0 ]]; then
  confirm "Install missing base Python packages into $PYTHON_BIN?" && pip_install_base "${base_pip_specs[@]}"
  write_runtime_env_file
  if [[ "$CHECK_ONLY" -eq 0 ]]; then
    log "Base packages were installed. Continuing dependency setup after rescan."
    exec bash "$0" "${ORIGINAL_ARGS[@]}"
  fi
fi

if [[ "${#missing_torch[@]}" -gt 0 ]]; then
  confirm "Install missing PyTorch packages into $PYTHON_BIN?" && pip_install_torch "${missing_torch[@]}"
fi

if [[ "${#missing_pip[@]}" -gt 0 ]]; then
  if [[ "$IS_AARCH64" -eq 1 && " ${missing_pip[*]} " == *" ${ULTRALYTICS_SPEC} "* ]]; then
    if confirm "Install Jetson-safe Ultralytics packages into $PYTHON_BIN?"; then
      pip_install_ignore_installed \
        "matplotlib==3.7.5" \
        "pillow==10.4.0" \
        "requests==2.32.4" \
        "scipy==1.10.1" \
        "psutil>=5.8.0" \
        "polars==1.8.2"
      pip_install_no_deps "ultralytics-thop==2.0.20" "$ULTRALYTICS_SPEC"
      "$PYTHON_BIN" -m pip install --force-reinstall --no-deps "$NUMPY_SPEC" "$PROTOBUF_SPEC"
    fi
  else
    confirm "Install missing pip packages into $PYTHON_BIN?" && pip_install_ignore_installed "${missing_pip[@]}"
  fi
fi

if [[ "$missing_viser" -eq 1 ]]; then
  confirm "Install Viser web viewer into $PYTHON_BIN?" && pip_install_viser
fi

if [[ "$need_pyzed_install" -eq 1 && "$pyzed_can_auto_install" -eq 1 ]]; then
  confirm "Install pyzed.sl into $PYTHON_BIN using the ZED SDK helper?" && install_zed_python_api
fi

if [[ "${#missing_apt[@]}" -gt 0 ]]; then
  install_apt_packages "${missing_apt[@]}"
fi

ensure_jetson_system_site_path

if [[ "${#missing_manual[@]}" -gt 0 ]]; then
  warn "Some dependencies require manual/system installation:"
  for item in "${missing_manual[@]}"; do
    warn "  - $item"
  done
fi

write_runtime_env_file
log "Done. Re-run with --check-only to verify the final environment."
if [[ -n "$PYTHON_BIN" ]]; then
  log "Use this Python for runtime scripts:"
  printf 'export SOCCER_PERCEPTION_PYTHON=%q\n' "$PYTHON_BIN"
fi
