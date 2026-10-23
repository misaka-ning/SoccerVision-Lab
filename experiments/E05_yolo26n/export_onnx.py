#!/usr/bin/env python3
"""Static FP32 raw one-to-many ONNX; numerically checked on CPU, no embedded NMS."""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import sys

from e05 import HERE, dump, load, now, run_path, runtime, sha, verify, check_nano


def export(run, smoke=False):
    torch = runtime(run)
    verify(run)
    # Isolated, optional export dependencies; never replace the training environment.
    deps = HERE/'.deps/ort'
    if deps.exists():
        sys.path.insert(0, str(deps))
    import numpy as np
    import onnx
    import onnxruntime as ort
    from ultralytics import YOLO
    from ultralytics.data.augment import LetterBox
    from ultralytics.nn.modules import Detect
    import cv2
    record = load(run/'run_record.json')
    checkpoint = run/('init.pt' if smoke else 'train/weights/best.pt')
    if not smoke:
        if record['status'] != 'trained' or sha(checkpoint) != record['training']['checkpoints']['best']['sha256']:
            raise ValueError('先完成训练并核对 best.pt；不能把初始化冒充正式候选')
    out = run/('precheck_onnx' if smoke else 'export')
    out.mkdir(exist_ok=False)
    dump(out/'status.json', dict(status='running', synthetic_initialization_only=smoke))
    try:
        model = YOLO(str(checkpoint), task='detect').model.cpu().float().eval()
        check_nano(model, 1)
        reference = deepcopy(model)
        reference.end2end = False
        model.end2end = False
        model.fuse(verbose=False)
        for item in model.modules():
            if isinstance(item, Detect):
                item.export, item.dynamic, item.format, item.xyxy, item.shape = True, False, 'onnx', False, None
        torch.manual_seed(42)
        probe = torch.rand(2,3,640,640)
        with torch.inference_mode():
            raw = model(probe)
        if list(raw.shape) != [2,5,8400] or raw.dtype != torch.float32:
            raise ValueError('静态 raw 输出接口不符')
        filename = out/'yolo26n_b2_fp32.onnx'
        with torch.inference_mode():
            torch.onnx.export(model, probe, str(filename), input_names=['images'], output_names=['output0'],
                              opset_version=17, dynamo=False, do_constant_folding=True,
                              dynamic_axes=None, export_params=True)
        graph = onnx.load(filename)
        onnx.checker.check_model(graph)
        shapes = {}
        for tensor, expected in ((graph.graph.input[0],[2,3,640,640]), (graph.graph.output[0],[2,5,8400])):
            actual = [d.dim_value for d in tensor.type.tensor_type.shape.dim]
            if actual != expected or tensor.type.tensor_type.elem_type != onnx.TensorProto.FLOAT:
                raise ValueError(f'ONNX shape/dtype 不符：{tensor.name}: {actual}')
            shapes[tensor.name] = actual
        if len(graph.graph.input) != 1 or len(graph.graph.output) != 1 or any(n.op_type == 'NonMaxSuppression' for n in graph.graph.node):
            raise ValueError('需要单输入输出且不含 NMS 的原始候选图')
        # Metadata is also readable by older Ultralytics; args.nms must be false for a raw exported graph.
        metadata = dict(description='E05 YOLO26n single-class raw one-to-many', task='detect', names={0:'football'},
                        stride=32, batch=2, imgsz=[640,640], end2end=False,
                        args=dict(dynamic=False, half=False, nms=False), channels=3)
        for key, value in metadata.items():
            item = graph.metadata_props.add()
            item.key, item.value = key, str(value)
        onnx.save(graph, filename)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(str(filename), sess_options=options, providers=['CPUExecutionProvider'])
        # Three changing inputs, including two real Val images; no Test data is read.
        from e05 import DATA
        selected = sorted((DATA/'images/val').iterdir())[:2]
        box = LetterBox(new_shape=(640,640), auto=False, scale_fill=False, scaleup=True, stride=32)
        real = np.stack([box(image=cv2.imread(str(p)))[:,:,::-1].transpose(2,0,1) for p in selected])
        inputs = [('zero', np.zeros((2,3,640,640), np.float32)),
                  ('random', probe.numpy()), ('real_val_pair', np.ascontiguousarray(real, dtype=np.float32)/255)]
        checks = []
        for label, array in inputs:
            with torch.inference_mode():
                baseline = reference(torch.from_numpy(array))[0].numpy()
            actual = session.run(['output0'], {'images':array})[0]
            coord = float(np.max(np.abs(actual[:,:4]-baseline[:,:4])))
            score = float(np.max(np.abs(actual[:,4:]-baseline[:,4:])))
            passed = bool(np.isfinite(actual).all() and coord <= .05 and score <= 1e-4)
            checks.append(dict(input=label, coordinate_max_abs_pixels=coord, score_max_abs=score, passed=passed))
            if not passed:
                raise ValueError(f'ONNX 数值校验失败：{checks[-1]}')
        verify(run)
        dump(out/'manifest.json', dict(utc=now(), checkpoint=str(checkpoint), checkpoint_sha256=sha(checkpoint),
             onnx=str(filename), onnx_sha256=sha(filename), shape=shapes, dtype='float32', opset=17,
             metadata=metadata, branch='one-to-many', embedded_nms=False, synthetic_initialization_only=smoke,
             numerical_checks=checks, numerical_tolerances=dict(coordinate_pixels=.05, score_absolute=1e-4),
             real_val_images=[dict(path=str(p),sha256=sha(p)) for p in selected],
             versions=dict(torch=torch.__version__, onnx=onnx.__version__, onnxruntime=ort.__version__),
             robot_tensorrt_build='not_run', deployment_accepted=False))
        dump(out/'status.json', dict(status='passed', synthetic_initialization_only=smoke))
        print(filename)
    except BaseException as exc:
        dump(out/'status.json', dict(status='failed', error=repr(exc), synthetic_initialization_only=smoke))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run')
    parser.add_argument('--smoke-init', action='store_true', help='仅验证未训练初始化的导出契约，不是正式模型')
    args = parser.parse_args()
    export(run_path(args.run), args.smoke_init)
