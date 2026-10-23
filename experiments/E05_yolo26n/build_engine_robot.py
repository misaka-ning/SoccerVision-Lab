#!/usr/bin/env python3
"""Run manually on the Jetson: build a NEW diagnostic engine from a checked E05 export."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import struct
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export-dir', type=Path, required=True, help='拷贝到机器人后的 export 目录，含 manifest.json 和 ONNX')
    parser.add_argument('--output-dir', type=Path, required=True, help='尚不存在的独立测试目录；不自动部署')
    args = parser.parse_args()
    manifest = json.loads((args.export_dir/'manifest.json').read_text())
    onnx = args.export_dir/Path(manifest['onnx']).name
    if manifest.get('synthetic_initialization_only') is not False or manifest.get('embedded_nms') is not False:
        raise ValueError('拒绝未训练初始化或非 raw one-to-many 导出')
    if sha(onnx) != manifest['onnx_sha256'] or not all(c['passed'] for c in manifest['numerical_checks']):
        raise ValueError('ONNX 内容或数值验收不符')
    if platform.machine() != 'aarch64':
        raise ValueError('必须在目标 Jetson 构建，不能复制 x86 TensorRT Engine 部署')
    import tensorrt as trt
    if not trt.__version__.startswith('8.5.2'):
        raise ValueError(f'此入口固定 E01 环境 TRT 8.5.2，实际 {trt.__version__}')
    args.output_dir.mkdir(parents=True, exist_ok=False)
    logger = trt.Logger(trt.Logger.INFO)
    started = time.perf_counter()
    with trt.Builder(logger) as builder, builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)) as network, builder.create_builder_config() as config, trt.OnnxParser(network, logger) as parser_onnx:
        if not parser_onnx.parse(onnx.read_bytes()):
            raise ValueError('\n'.join(str(parser_onnx.get_error(i)) for i in range(parser_onnx.num_errors)))
        if (network.num_inputs, network.num_outputs) != (1,1) or tuple(network.get_input(0).shape) != (2,3,640,640) or tuple(network.get_output(0).shape) != (2,5,8400):
            raise ValueError('TensorRT 网络输入输出不符')
        if not builder.platform_has_fast_fp16:
            raise ValueError('当前设备没有预期 FP16 支持')
        config.set_flag(trt.BuilderFlag.FP16)
        config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 2 << 30)
        serialized = builder.build_serialized_network(network, config)
        if serialized is None:
            raise RuntimeError('TensorRT 构建失败；保留日志，不自动换配置')
        raw = bytes(serialized)
    with trt.Runtime(logger) as runtime:
        engine = runtime.deserialize_cuda_engine(raw)
        if engine is None or engine.num_bindings != 2:
            raise ValueError('Engine 反序列化或 binding 数量不符')
        bindings = [dict(name=engine.get_binding_name(i), shape=list(engine.get_binding_shape(i)),
                         dtype=str(engine.get_binding_dtype(i)), is_input=bool(engine.binding_is_input(i))) for i in range(2)]
        expected = {True:[2,3,640,640], False:[2,5,8400]}
        if {b['is_input'] for b in bindings} != {True,False} or any(b['shape'] != expected[b['is_input']] or engine.get_binding_dtype(i) != trt.float32 for i,b in enumerate(bindings)):
            raise ValueError('Engine 必须固定 batch2 和 FP32 I/O')
    plan = args.output_dir/'E05_yolo26n_b2_fp16.plan'
    plan.write_bytes(raw)
    # Ultralytics .engine header: 4-byte metadata size + UTF8 JSON + TensorRT bytes.
    metadata = manifest['metadata']
    header = json.dumps(metadata, ensure_ascii=False).encode('utf-8')
    wrapped = args.output_dir/'E05_yolo26n_b2_fp16.engine'
    wrapped.write_bytes(struct.pack('<I',len(header)) + header + raw)
    result = dict(utc=datetime.now(timezone.utc).isoformat(), tensorrt=trt.__version__, onnx_sha256=sha(onnx),
                  engine_sha256=sha(wrapped), plan_sha256=sha(plan), bindings=bindings,
                  fp16_tactics=True, workspace_bytes=2 << 30, build_seconds=time.perf_counter()-started,
                  numerical_trt_validation='not_run', system_ab='not_run', deployed=False)
    (args.output_dir/'build.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(wrapped)
    print('仅构建独立候选；尚未通过 TRT 数值/检测/双目定位与系统 A/B 验收，不修改生产 YAML。')


if __name__ == '__main__':
    main()
