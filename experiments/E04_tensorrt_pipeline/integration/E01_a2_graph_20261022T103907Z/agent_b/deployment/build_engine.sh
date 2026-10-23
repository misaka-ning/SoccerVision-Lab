#!/usr/bin/env bash
# Explicitly build/reuse an engine in the shared model directory on this Jetson.
set -e
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
soccer_load_runtime yes
"$SOCCER_PERCEPTION_PYTHON" - "$@" <<'PY'
import argparse
from dataclasses import replace
parser = argparse.ArgumentParser(description='Build an engine in the shared model directory.')
mode = parser.add_mutually_exclusive_group()
mode.add_argument('--force', action='store_true', help='Explicitly rebuild and replace an existing engine')
mode.add_argument('--adopt-existing', action='store_true',
                  help='Record current settings for a legacy engine you have verified matches them')
args = parser.parse_args()
from ultralytics import YOLO
from soccer_perception.ros.node import config_from_ros_params
from soccer_perception.pipeline import PipelineFactory
config = config_from_ros_params()
# A 2 GiB workspace leaves room for other processes on this 16 GB Jetson.
config = replace(config, yolo_tensorrt=True,
                 yolo_trt_workspace_gb=config.yolo_trt_workspace_gb or 2.0)
detector = PipelineFactory(config)._create_detector()
engine_path = detector.build_engine(YOLO, force=args.force, adopt_existing=args.adopt_existing)
print('TensorRT engine ready:', engine_path)
PY
