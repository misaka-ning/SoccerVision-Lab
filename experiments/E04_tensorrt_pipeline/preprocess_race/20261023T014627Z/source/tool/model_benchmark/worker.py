"""One model per process. Never imports GPU libraries in the parent controller."""
import argparse
import csv
import hashlib
import json
import os
import signal
import struct
import time
from pathlib import Path

from reporting import write_json

STOP = False


def stop(signum, frame):
    global STOP
    STOP = True


class Progress:
    def __init__(self, directory):
        self.directory = directory
        self.last = 0.0
        self.stage = None
        self.data = {}

    def set(self, stage, force=False, **values):
        now = time.monotonic()
        self.data.update(values)
        self.data.update(stage=stage, pid=os.getpid(), heartbeat=now)
        # Stage changes are useful for diagnosing a stall. CPU overhead is included
        # in system throughput; per-frame metrics themselves are measured before IO.
        if force or now-self.last >= .5:
            write_json(self.directory/'progress.json', self.data)
            self.last = now
        self.stage = stage


def engine_bytes(path):
    with open(path, 'rb') as f:
        prefix = f.read(4)
        n = struct.unpack('<I', prefix)[0] if len(prefix) == 4 else 0
        if 0 < n < min(1048576, os.path.getsize(path)-4):
            try:
                metadata = json.loads(f.read(n).decode('utf-8'))
                if isinstance(metadata, dict):
                    return metadata, f.read()
            except (ValueError, UnicodeError):
                pass
        f.seek(0)
        return {}, f.read()


class Engine:
    def __init__(self, path, requested):
        import numpy as np
        import tensorrt as trt
        import torch
        self.torch = torch
        self.trt = trt
        self.metadata, blob = engine_bytes(path)
        self.logger = trt.Logger(trt.Logger.WARNING)
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(blob)
        if self.engine is None:
            raise ValueError('Engine 反序列化失败；请检查 TensorRT/GPU 兼容性')
        e = self.engine
        self.v3 = not hasattr(e, 'num_bindings')
        self.io = []
        count = e.num_io_tensors if self.v3 else e.num_bindings // max(1, e.num_optimization_profiles)
        if not self.v3 and e.has_implicit_batch_dimension:
            raise ValueError('仅支持 explicit-batch Engine')
        for i in range(count):
            name = e.get_tensor_name(i) if self.v3 else e.get_binding_name(i)
            inp = e.get_tensor_mode(name) == trt.TensorIOMode.INPUT if self.v3 else e.binding_is_input(i)
            shape = list(e.get_tensor_shape(name) if self.v3 else e.get_binding_shape(i))
            dtype = np.dtype(trt.nptype(e.get_tensor_dtype(name) if self.v3 else e.get_binding_dtype(i)))
            location = e.get_tensor_location(name) if self.v3 else e.get_location(i)
            if location != trt.TensorLocation.DEVICE:
                raise ValueError('不支持 CPU binding: ' + name)
            if not self.v3 and e.is_shape_binding(i):
                raise ValueError('不支持 shape binding: ' + name)
            self.io.append(dict(index=i, name=name, input=bool(inp), shape=shape, dtype=str(dtype)))
        inputs = [x for x in self.io if x['input']]
        if len(inputs) != 1 or len(inputs[0]['shape']) != 4:
            raise ValueError('当前工具支持单个 NCHW 图像输入 Engine')
        inp = inputs[0]; shape = inp['shape']
        profile = None
        if -1 in shape:
            profile = [list(x) for x in (e.get_tensor_profile_shape(inp['name'], 0) if self.v3 else e.get_profile_shape(0, inp['index']))]
            if requested == 'auto':
                raise ValueError('动态 Engine 请设置 test.input_shape；profile 0 min/opt/max=' + str(profile))
            actual = requested
            if any(not lo <= v <= hi for v,lo,hi in zip(actual,profile[0],profile[2])):
                raise ValueError('input_shape 超出 profile 0 范围: ' + str(profile))
        else:
            actual = shape if requested == 'auto' else requested
            if list(actual) != shape:
                raise ValueError('固定 Engine 输入为 %s，配置为 %s' % (shape, actual))
        if actual[1] != 3 or inp['dtype'] not in ('float16', 'float32'):
            raise ValueError('仅支持 3 通道 float16/float32 图像输入')
        self.shape = list(actual)
        self.context = e.create_execution_context()
        if self.context is None:
            raise RuntimeError('无法创建 TensorRT execution context')
        if profile:
            ok = self.context.set_input_shape(inp['name'], actual) if self.v3 else self.context.set_binding_shape(inp['index'], actual)
            if not ok:
                raise ValueError('设置动态形状失败')
        for item in self.io:
            item['runtime_shape'] = list(self.context.get_tensor_shape(item['name']) if self.v3 else self.context.get_binding_shape(item['index']))
            if any(x <= 0 for x in item['runtime_shape']):
                raise ValueError('不支持数据相关的动态输出尺寸: ' + str(item))
        self.info = dict(path=str(path), sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                         input_shape=self.shape, bindings=self.io, profile_0=profile, metadata=self.metadata,
                         precision_note='I/O dtype 和导出 metadata 不等价于所有内部层精度；以原始构建记录为准',
                         tensorrt_version=trt.__version__)

    def allocate(self, seed):
        import numpy as np
        torch = self.torch
        torch.manual_seed(seed)
        self.tensors = []
        self.addresses = [0] * (self.engine.num_bindings if not self.v3 else len(self.io))
        for item in self.io:
            dtype = torch.from_numpy(np.empty((), dtype=item['dtype'])).dtype
            t = torch.empty(item['runtime_shape'], device='cuda:0', dtype=dtype)
            if item['input']:
                t.uniform_(0, 1)
            self.tensors.append(t)
            self.addresses[item['index']] = t.data_ptr()
            if self.v3:
                self.context.set_tensor_address(item['name'], t.data_ptr())
        torch.cuda.synchronize()
        self.stream = torch.cuda.Stream()
        self.start = torch.cuda.Event(enable_timing=True)
        self.end = torch.cuda.Event(enable_timing=True)

    def execute(self):
        torch = self.torch
        wall = time.perf_counter()
        with torch.cuda.stream(self.stream):
            self.start.record(self.stream)
            if self.v3:
                ok = self.context.execute_async_v3(self.stream.cuda_stream)
            else:
                ok = self.context.execute_async_v2(self.addresses, self.stream.cuda_stream)
            if not ok:
                raise RuntimeError('TensorRT execution failed')
            self.end.record(self.stream)
        self.end.synchronize()
        return self.start.elapsed_time(self.end), (time.perf_counter()-wall)*1000


class Records:
    def __init__(self, directory, fields):
        self.f = (directory/'frames.csv').open('w', newline='', buffering=65536, encoding='utf-8')
        self.writer = csv.DictWriter(self.f, fields)
        self.writer.writeheader()
        self.count = 0
        self.total = 0.0
        self.last_flush = time.monotonic()

    def add(self, row, metric):
        self.writer.writerow(row)
        self.count += 1
        self.total += row[metric]
        if time.monotonic()-self.last_flush > 1:
            self.f.flush()
            self.last_flush = time.monotonic()

    def close(self):
        self.f.close()


def engine_run(cfg, model, directory, progress):
    progress.set('加载 Engine', force=True, completed=0)
    engine = Engine(model['path'], cfg['test']['input_shape'])
    write_json(directory/'engine_info.json', engine.info)
    engine.allocate(cfg['test']['seed'])
    warm = cfg['test']['warmup_iterations']
    progress.set('预热', force=True, warmup_total=warm, completed=0)
    for i in range(warm):
        if STOP: return False
        engine.execute()
        progress.set('预热', completed=i+1)
    records = Records(directory, ['sample', 'engine_ms', 'execute_wall_ms'])
    begin = time.monotonic()
    progress.set('测量', force=True, completed=0, elapsed=0)
    try:
        while time.monotonic()-begin < cfg['test']['duration_seconds'] and not STOP:
            gpu, wall = engine.execute()
            records.add(dict(sample=records.count, engine_ms=gpu, execute_wall_ms=wall), 'engine_ms')
            progress.set('测量', completed=records.count, elapsed=time.monotonic()-begin,
                         mean_ms=records.total/records.count)
    finally:
        records.close()
    return not STOP and records.count > 0


def system_run(cfg, model, directory, progress, info):
    # Import the actual installed production loop. Instrument its objects locally;
    # do not copy the loop or modify installed files.
    from dataclasses import replace
    import rclpy
    import soccer_perception.ros.node as node
    import soccer_perception
    from soccer_perception.resources import deployment_config_path
    shape = info['input_shape']
    if shape[0] != 2:
        raise ValueError('system 模式要求双目 batch=2')
    if not info['metadata']:
        raise ValueError('system 模式需要当前 Ultralytics 可加载的、含元数据的 YOLO Engine；原始 TRT Engine 可用 engine 模式')
    progress.set('初始化 ROS', force=True, completed=0)
    overrides = dict(cfg['system']['parameter_overrides'])
    rate = cfg['system']['publish_rate_hz']
    overrides.update(yolo_model=Path(model['path']), yolo_engine_path=Path(model['path']),
                     yolo_tensorrt=True, yolo_trt_batch=2, imgsz=shape[2],
                     zed_viser_enabled=cfg['system']['viser_enabled'],
                     zed_viser_show_point_cloud=cfg['system']['point_cloud_enabled'])
    if rate is not None:
        overrides['deploy_packet_rate_hz'] = rate
    base_config = node.config_from_ros_params()
    unknown = set(overrides) - set(vars(base_config))
    if unknown:
        raise ValueError('未知部署参数: ' + str(sorted(unknown)))
    # Reuse the production type validator for override values.
    from dataclasses import fields
    for field in fields(base_config):
        if field.name in cfg['system']['parameter_overrides']:
            value = node._parameter_scalar(field, overrides[field.name])
            kind = str(field.type).split(' | ')[0]
            optional = 'None' in str(field.type)
            if kind == 'Path':
                from soccer_perception.resources import resolve_resource_path
                value = None if optional and value.lower() in ('', 'none', 'null', 'unchanged') else resolve_resource_path(value)
            elif optional and kind == 'int' and field.name.startswith('zed_'):
                value = None if value == 'unchanged' else value
            elif optional and kind in ('int', 'float') and value < 0:
                value = None
            overrides[field.name] = value
    config = replace(base_config, **overrides)
    write_json(directory/'deployment_config.json', dict(
        parameters={k: str(v) if isinstance(v, Path) else v for k,v in vars(config).items()},
        package=soccer_perception.__file__, manifest=str(deployment_config_path()),
        publish_rate_hz=rate, input_shape=shape, ros_domain_id=os.environ.get('ROS_DOMAIN_ID')))
    code_root = Path(soccer_perception.__file__).parent
    write_json(directory/'deployment_code_hashes.json', {str(p.relative_to(code_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code_root.rglob('*.py')})
    node.config_from_ros_params = lambda ros_node=None: config
    fields = ['sample', 'cycle_start', 'cycle_end', 'publish_end', 'read_ms', 'detector_ms',
              'pipeline_ms', 'read_ready_to_publish_ms', 'read_start_to_publish_ms',
              'visualization_ms', 'cycle_ms']
    records = Records(directory, fields)
    state = dict(warm=0, begin=None, done=False, row={}, phase='预热')
    warm = cfg['test']['warmup_iterations']
    original_factory = node.PipelineFactory
    original_scheduler = node.OutputScheduler
    original_publisher = node.RosBallStatePublisher
    schedulers = []

    def stage(name):
        progress.set(state['phase'] + '/' + name, completed=records.count if state['begin'] else state['warm'],
                     elapsed=time.monotonic()-state['begin'] if state['begin'] else 0)

    class Scheduler(original_scheduler):
        def __init__(self, hz):
            super().__init__(hz); schedulers.append(self)
        def wait(self):
            stage('调度等待')
            if rate is not None: super().wait()

    class Publisher(original_publisher):
        def publish(self, *args, **kwargs):
            stage('ROS 发布')
            result = super().publish(*args, **kwargs)
            state['row']['publish_end'] = time.monotonic()
            return result
        def publish_status_only(self, *args, **kwargs):
            stage('ROS 发布')
            result = super().publish_status_only(*args, **kwargs)
            state['row']['publish_end'] = time.monotonic()
            return result

    class Factory(original_factory):
        def create(self):
            pipeline = super().create()
            old_read = pipeline.source.read
            def read():
                stage('相机读取')
                state['read_start'] = time.monotonic()
                result = old_read()
                state['read_ready'] = time.monotonic()
                state['row']['read_ms'] = (state['read_ready']-state['read_start'])*1000
                return result
            pipeline.source.read = read
            old_load = pipeline.detector.load
            def load():
                progress.set('加载 Engine', force=True)
                old_load()
                old_predict = pipeline.detector.model.predict
                def predict(*args, **kwargs):
                    kwargs.update(imgsz=shape[2:], rect=False)
                    return old_predict(*args, **kwargs)
                pipeline.detector.model.predict = predict
            pipeline.detector.load = load
            old_detect = pipeline.detector.detect_candidates_batch
            def detect(*args, **kwargs):
                stage('检测')
                t = time.monotonic()
                result = old_detect(*args, **kwargs)
                state['row']['detector_ms'] = (time.monotonic()-t)*1000
                backend = pipeline.detector.model.predictor.model
                actual = list(backend.bindings['images'].shape)
                if not backend.engine or actual != shape:
                    raise ValueError('实际后端/形状不符合要求: ' + str(actual))
                return result
            pipeline.detector.detect_candidates_batch = detect
            old_next = pipeline.next_packet
            def next_packet():
                state['row'] = dict(cycle_start=time.monotonic())
                stage('流水线')
                packet = old_next()
                state['row']['pipeline_ms'] = (time.monotonic()-state['row']['cycle_start'])*1000
                return packet
            pipeline.next_packet = next_packet
            old_vis = pipeline.update_visualization
            def visualization(packet):
                stage('Viser')
                t = time.monotonic()
                old_vis(packet)
                end = time.monotonic()
                row = state['row']
                row.update(cycle_end=end, visualization_ms=(end-t)*1000,
                           cycle_ms=(end-row['cycle_start'])*1000,
                           read_ready_to_publish_ms=(row['publish_end']-state['read_ready'])*1000,
                           read_start_to_publish_ms=(row['publish_end']-state['read_start'])*1000,
                           sample=records.count)
                if state['begin'] is None:
                    state['warm'] += 1
                    progress.set('预热', completed=state['warm'], warmup_total=warm)
                    if state['warm'] >= warm:
                        for scheduler in schedulers: scheduler.start()
                        state['begin'] = time.monotonic()
                        state['phase'] = '测量'
                        progress.set('测量', force=True, completed=0, elapsed=0)
                else:
                    records.add(row, 'read_ready_to_publish_ms')
                    elapsed = end-state['begin']
                    progress.set('测量', completed=records.count, elapsed=elapsed,
                                 mean_ms=records.total/records.count, processing_hz=records.count/elapsed)
                    state['done'] = elapsed >= cfg['test']['duration_seconds']
            pipeline.update_visualization = visualization
            return pipeline

    node.PipelineFactory = Factory
    node.OutputScheduler = Scheduler
    node.RosBallStatePublisher = Publisher
    old_continue = node._ros_should_continue
    node._ros_should_continue = lambda ros_node: not STOP and not state['done'] and old_continue(ros_node)
    rclpy.init(args=[])
    ros_node = rclpy.create_node('soccer_model_benchmark')
    try:
        node.run_ros_node(ros_node)
    finally:
        records.close()
        ros_node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()
    return state['done'] and not STOP


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('job')
    args = parser.parse_args()
    # Linux: prevent an orphan worker if the controller is killed unexpectedly.
    import ctypes
    parent = os.getppid()
    if ctypes.CDLL(None).prctl(1, signal.SIGTERM) != 0:
        raise RuntimeError('无法启用父进程退出保护')
    if parent == 1 or os.getppid() != parent:
        return 130
    job = json.loads(Path(args.job).read_text(encoding='utf-8'))
    directory = Path(job['directory'])
    progress = Progress(directory)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    progress.set('启动', force=True, completed=0)
    try:
        if job.get('info'):
            current_hash = hashlib.sha256(Path(job['model']['path']).read_bytes()).hexdigest()
            if current_hash != job['info']['sha256']:
                raise ValueError('Engine 文件在检查后被修改，停止测试')
        if job['mode'] == 'inspect':
            progress.set('检查 Engine', force=True)
            engine = Engine(job['model']['path'], job['config']['test']['input_shape'])
            write_json(directory/'engine_info.json', engine.info)
            complete = True
        elif job['mode'] == 'engine':
            complete = engine_run(job['config'], job['model'], directory, progress)
        else:
            complete = system_run(job['config'], job['model'], directory, progress, job['info'])
        write_json(directory/'result.json', dict(status='complete' if complete else 'interrupted'))
        progress.set('完成' if complete else '中断', force=True)
        return 0 if complete else 130
    except Exception as exc:
        import traceback
        traceback.print_exc()
        write_json(directory/'result.json', dict(status='failed', error=str(exc)))
        progress.set('失败', force=True, error=str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
