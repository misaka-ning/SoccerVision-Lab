#!/usr/bin/env bash
# Deployment version policy. Sourced after IS_AARCH64 is detected.
REQUIRED_PYTHON_VERSION="3.8"
if [[ "$IS_AARCH64" -eq 1 ]]; then
  # JetPack TensorRT Python bindings still reference np.bool; NumPy 1.24 removed it.
  NUMPY_SPEC="${NUMPY_SPEC:-numpy==1.23.5}"
else
  NUMPY_SPEC="${NUMPY_SPEC:-numpy==1.24.4}"
fi
# Read shared pins without importing Python or changing the caller's cwd.
SOCCER_REQUIREMENTS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../requirements" && pwd)"
while IFS= read -r spec; do
  case "$spec" in
    opencv-python==*) OPENCV_SPEC="$spec" ;;
    PyYAML==*) PYYAML_SPEC="$spec" ;;
  esac
done < "$SOCCER_REQUIREMENTS_DIR/common.txt"
: "${OPENCV_SPEC:?Missing opencv-python pin in requirements/common.txt}"
: "${PYYAML_SPEC:?Missing PyYAML pin in requirements/common.txt}"
ULTRALYTICS_SPEC="ultralytics==8.4.63"
TORCH_SPEC="torch==2.4.1"
TORCHVISION_SPEC="torchvision==0.19.1"
REQUESTS_SPEC="${REQUESTS_SPEC:-requests==2.32.3}"
PROTOBUF_SPEC="${PROTOBUF_SPEC:-protobuf==3.20.3}"
ONNX_SPEC="${ONNX_SPEC:-onnx==1.17.0}"
ONNXSLIM_SPEC="${ONNXSLIM_SPEC:-onnxslim==0.1.94}"
TENSORRT_SPEC="${TENSORRT_SPEC:-tensorrt==11.1.0.106}"
VISER_SPEC="${VISER_SPEC:-viser==1.0.30}"
