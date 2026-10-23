"""CPU-only controller: lock -> inspect sequentially -> round robin workers."""
import argparse
import datetime
import fcntl
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml
from reporting import generate, write_json

HERE = Path(__file__).resolve().parent
LOCK_FD = None


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for k, v in node.value:
        key = loader.construct_object(k, deep=deep)
        if key in result: raise ValueError('YAML 重复字段: ' + str(key))
        result[key] = loader.construct_object(v, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def load_config(path):
    cfg = yaml.load(path.read_text(encoding='utf-8'), Loader=UniqueLoader)
    schema = {
        'test': {'mode', 'rounds', 'warmup_iterations', 'duration_seconds', 'input_shape', 'seed'},
        'system': {'publish_rate_hz', 'viser_enabled', 'point_cloud_enabled', 'ros_domain_id', 'parameter_overrides'},
        'monitor': {'progress_interval_seconds', 'stall_warning_seconds', 'stall_timeout_seconds', 'startup_timeout_seconds', 'shutdown_timeout_seconds'},
        'output': {'directory', 'save_frame_records'}}
    allowed = set(schema) | {'models', 'baseline'}
    if not isinstance(cfg, dict) or set(cfg)-allowed:
        raise ValueError('无效配置顶层字段')
    defaults = yaml.load((HERE/'config.yaml').read_text(encoding='utf-8'), Loader=UniqueLoader)
    for section, keys in schema.items():
        value = cfg.get(section, {})
        if not isinstance(value, dict) or set(value)-keys:
            raise ValueError('未知配置字段: ' + section)
        cfg[section] = dict(defaults[section], **value)
    models = cfg.get('models')
    if not isinstance(models, list) or not models: raise ValueError('models 必须为非空列表')
    names = set()
    for model in models:
        if not isinstance(model, dict) or set(model) != {'name', 'path'} or not isinstance(model['name'], str) or not re.fullmatch(r'[A-Za-z0-9_-]+', model['name']):
            raise ValueError('model 需要 name/path；name 只允许英文、数字、下划线和连字符')
        if model['name'] in names: raise ValueError('模型名称重复')
        names.add(model['name'])
        p = (path.parent / Path(model['path']).expanduser()).resolve()
        if p.suffix.lower() != '.engine' or not p.is_file(): raise ValueError('Engine 不存在: ' + str(p))
        model['path'] = str(p)
    cfg.setdefault('baseline', models[0]['name'])
    if cfg['baseline'] not in names: raise ValueError('baseline 不在 models 中')
    test = cfg['test']
    if test['mode'] not in ('engine', 'system', 'both'): raise ValueError('mode 必须是 engine/system/both')
    for field in ('rounds', 'warmup_iterations', 'seed'):
        v = test[field]
        if type(v) is not int or v < (0 if field == 'seed' else 1): raise ValueError(field+' 不是有效整数')
    def positive(v): return type(v) in (int,float) and math.isfinite(v) and v > 0
    if not positive(test['duration_seconds']): raise ValueError('duration_seconds 必须为正数')
    shape = test['input_shape']
    if shape != 'auto' and (not isinstance(shape, list) or len(shape)!=4 or any(type(x) is not int or x<=0 for x in shape)):
        raise ValueError('input_shape 必须为 auto 或 [N,C,H,W]')
    for k,v in cfg['monitor'].items():
        if not positive(v): raise ValueError(k+' 必须为正数')
    if cfg['monitor']['stall_warning_seconds'] >= cfg['monitor']['stall_timeout_seconds']:
        raise ValueError('stall_warning_seconds 必须小于 stall_timeout_seconds')
    system = cfg['system']
    if system['publish_rate_hz'] is not None and not positive(system['publish_rate_hz']): raise ValueError('publish_rate_hz 必须为正数或 null')
    for k in ('viser_enabled', 'point_cloud_enabled'):
        if type(system[k]) is not bool: raise ValueError(k+' 必须为布尔值')
    if type(cfg['output']['save_frame_records']) is not bool: raise ValueError('save_frame_records 必须为布尔值')
    if type(system['ros_domain_id']) is not int or not 0 <= system['ros_domain_id'] <= 232: raise ValueError('无效 ROS domain ID')
    overrides = system['parameter_overrides']
    protected = {'yolo_model', 'yolo_engine_path', 'yolo_tensorrt', 'yolo_trt_batch', 'imgsz', 'device', 'half', 'deploy_packet_rate_hz', 'zed_viser_enabled', 'zed_viser_show_point_cloud'}
    if not isinstance(overrides, dict) or protected.intersection(overrides): raise ValueError('parameter_overrides 含工具管理的字段')
    cfg['output']['directory'] = str((path.parent/Path(cfg['output']['directory']).expanduser()).resolve())
    return cfg


def command_output(args):
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5)
        return p.stdout.strip()
    except Exception as exc:
        return str(exc)


def environment():
    from importlib import metadata
    versions = {}
    for name in ('torch', 'torchvision', 'tensorrt', 'ultralytics', 'viser', 'PyYAML'):
        try: versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError: versions[name] = 'unknown'
    return dict(python=sys.executable, versions=versions,
                power_mode=command_output(['/usr/sbin/nvpmodel', '-q']),
                clocks=command_output(['/usr/bin/jetson_clocks', '--show']),
                processes=command_output(['ps', '-eo', 'pid,pcpu,pmem,comm']),
                system=command_output(['uname', '-a']))


def telemetry():
    result = {'monotonic': time.monotonic(), 'temperatures_millicelsius': {}, 'frequencies_hz_or_khz': {}}
    for p in Path('/sys/class/thermal').glob('thermal_zone*/temp'):
        try: result['temperatures_millicelsius'][(p.parent/'type').read_text(encoding='utf-8').strip()] = int(p.read_text(encoding='utf-8'))
        except (OSError, ValueError): pass
    paths = list(Path('/sys/devices/system/cpu').glob('cpufreq/policy*/scaling_cur_freq'))
    paths += list(Path('/sys/class/devfreq').glob('*/cur_freq'))
    for p in paths:
        try: result['frequencies_hz_or_khz'][str(p)] = int(p.read_text(encoding='utf-8'))
        except (OSError, ValueError): pass
    return result


def stop_group(proc, timeout):
    # Own process group only; never terminate other robot applications.
    try: os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError: pass
    deadline = time.monotonic()+timeout
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(.1)
    try: os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError: pass
    try: proc.wait(timeout=5)
    except subprocess.TimeoutExpired: raise RuntimeError('工作进程无法退出，停止所有后续测试')
    # Also verify no descendants retain the process group / GPU resources.
    deadline = time.monotonic()+5
    while time.monotonic() < deadline:
        try: os.killpg(proc.pid, 0)
        except ProcessLookupError: return
        time.sleep(.1)
    raise RuntimeError('工作进程组未完全释放，停止后续测试')


def run_worker(root, cfg, model, mode, round_no, info=None):
    directory = root / ('inspect_'+model['name'] if mode == 'inspect' else '%02d_%s_%s' % (round_no, model['name'], mode))
    directory.mkdir()
    job = dict(config=cfg, model=model, mode=mode, round=round_no, directory=str(directory), info=info)
    write_json(directory/'job.json', job)
    record = dict(model=model['name'], mode=mode, round=round_no, directory=str(directory), status='failed')
    env = dict(os.environ, ROS_DOMAIN_ID=str(cfg['system']['ros_domain_id']), PYTHONUNBUFFERED='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1', YOLO_AUTOINSTALL='false')
    tag = '[%s][%s][轮%d]' % (model['name'], mode, round_no)
    with (directory/'worker.log').open('w', encoding='utf-8') as log, (directory/'telemetry.jsonl').open('w', encoding='utf-8') as tele:
        proc = subprocess.Popen([sys.executable, '-u', str(HERE/'worker.py'), str(directory/'job.json')], stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True, pass_fds=(() if LOCK_FD is None else (LOCK_FD,)))
        print(tag+' 启动 PID='+str(proc.pid), flush=True)
        started = last_change = last_print = time.monotonic()
        last_count = None
        data = {}
        try:
            while proc.poll() is None:
                now = time.monotonic()
                try: data = json.loads((directory/'progress.json').read_text(encoding='utf-8'))
                except (OSError, ValueError): pass
                # Heartbeat/stage transitions alone do not count as completed work.
                count = (str(data.get('stage','')).startswith('测量'), data.get('completed', 0))
                if count != last_count:
                    last_count = count; last_change = now
                measuring_or_warming = any(x in data.get('stage','') for x in ('测量','预热'))
                limit = cfg['monitor']['stall_timeout_seconds'] if measuring_or_warming else cfg['monitor']['startup_timeout_seconds']
                if now-last_print >= cfg['monitor']['progress_interval_seconds']:
                    msg = '%s %s | 已用时 %.0fs | 完成 %s | %.0fs 无新完成' % (tag, data.get('stage','启动'), now-started, data.get('completed',0), now-last_change)
                    if 'elapsed' in data and (count[0] or data.get('stage') == '完成'): msg += ' | 测量 %.1f/%ss' % (data['elapsed'], cfg['test']['duration_seconds'])
                    if 'warmup_total' in data and data.get('stage','').startswith('预热'): msg += ' | 预热目标 %s' % data['warmup_total']
                    if 'mean_ms' in data: msg += ' | 均值 %.3fms' % data['mean_ms']
                    if 'processing_hz' in data: msg += ' | %.2fHz' % data['processing_hz']
                    if now-last_change >= cfg['monitor']['stall_warning_seconds']: msg += ' [警告：进程存活但无进展]'
                    print(msg, flush=True)
                    tele.write(json.dumps(telemetry())+'\n'); tele.flush()
                    last_print = now
                if now-last_change > limit:
                    record['status'] = 'timeout'
                    print(tag+' 超时，结束工作进程并保留已有结果', flush=True)
                    break
                time.sleep(.1)
        except KeyboardInterrupt:
            record['status'] = 'interrupted'
        finally:
            previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
            previous_term = signal.signal(signal.SIGTERM, signal.SIG_IGN)
            previous_hup = signal.signal(signal.SIGHUP, signal.SIG_IGN)
            try:
                stop_group(proc, cfg['monitor']['shutdown_timeout_seconds'])
            finally:
                signal.signal(signal.SIGINT, previous)
                signal.signal(signal.SIGTERM, previous_term)
                signal.signal(signal.SIGHUP, previous_hup)
        if record['status'] not in ('timeout','interrupted'):
            try:
                result = json.loads((directory/'result.json').read_text(encoding='utf-8'))
                record.update(result)
                if proc.returncode != 0 and record['status']=='complete': record['status']='failed'
            except (OSError, ValueError): record['error']='worker 未生成完成标记；查看 worker.log'
    print(tag+' '+record['status']+'；工作进程组已退出', flush=True)
    if record['status'] not in ('complete','interrupted'):
        tail = (directory/'worker.log').read_text(errors='replace').splitlines()[-14:]
        print('\n'.join(tail), flush=True)
    write_json(directory/'controller_result.json', record)
    return record


def compare_infos(infos, cfg):
    values = list(infos.values())
    def signature(info):
        meta = info['metadata']; args = meta.get('args', {})
        return dict(shape=info['input_shape'], io=[(b['input'],b['runtime_shape'],b['dtype']) for b in info['bindings']],
                    half=args.get('half'), int8=args.get('int8'), nms=args.get('nms'),
                    end2end=meta.get('end2end'), task=meta.get('task'), names=meta.get('names'))
    ref = signature(values[0])
    for info in values[1:]:
        if signature(info) != ref: raise ValueError('Engine 输入/输出/已知精度或后处理元数据不一致，拒绝直接对比；可分别做单模型测试')
    if cfg['test']['mode'] != 'engine':
        for info in values:
            if info['input_shape'][0] != 2: raise ValueError('system 模式要求 batch=2')
            if not info['metadata']: raise ValueError('system 模式要求 Ultralytics YOLO 元数据')
    for name,info in infos.items():
        print('[检查] %s | shape=%s | I/O=%s | 导出参数=%s' % (name,info['input_shape'],[(b['name'],b['dtype']) for b in info['bindings']],info['metadata'].get('args', 'unknown')), flush=True)
    if cfg['test']['mode'] != 'engine':
        print('[系统] 发布上限=%s Hz；Viser=%s；ROS_DOMAIN_ID=%s' % (cfg['system']['publish_rate_hz'], cfg['system']['viser_enabled'], cfg['system']['ros_domain_id']), flush=True)
    print('[提示] I/O dtype/导出元数据不能证明所有内部层精度；请保持原始构建条件一致。', flush=True)


def main():
    global LOCK_FD
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    parser = argparse.ArgumentParser(description='Existing TensorRT engines only; one worker at a time')
    parser.add_argument('--config', type=Path, default=HERE/'config.yaml')
    parser.add_argument('--check', action='store_true', help='只校验配置和逐个读取 Engine，仍会短暂创建 GPU context')
    parser.add_argument('--mode', choices=['engine','system','both'])
    parser.add_argument('--rounds', type=int)
    parser.add_argument('--duration', type=float)
    parser.add_argument('--warmup', type=int)
    args = parser.parse_args()
    cfg = load_config(args.config.resolve())
    for key, value in [('mode',args.mode),('rounds',args.rounds),('duration_seconds',args.duration),('warmup_iterations',args.warmup)]:
        if value is not None:
            if key != 'mode' and (not math.isfinite(value) or value<=0): parser.error(key+' 必须为正数')
            cfg['test'][key] = value
    # Machine-wide per-user lock, independent of config or output directory.
    lock = open('/tmp/soccer_model_benchmark_%d.lock' % os.getuid(), 'a+')
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: raise RuntimeError('已有测试主控正在运行，请等待其退出')
    LOCK_FD = lock.fileno()
    root = Path(cfg['output']['directory']) / (datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid()))
    root.mkdir(parents=True)
    (root/'config_resolved.yaml').write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
    write_json(root/'environment.json', environment())
    write_json(root/'tool_hashes.json', {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')})
    class Tee:
        def __init__(self, stream, f): self.stream,self.f=stream,f
        def write(self,s): self.stream.write(s); self.f.write(s); self.f.flush()
        def flush(self): self.stream.flush(); self.f.flush()
    original = sys.stdout
    logfile = (root/'progress.log').open('w', encoding='utf-8')
    sys.stdout = Tee(original,logfile)
    jobs=[]; overall='failed'
    print('[任务] 输出目录 '+str(root), flush=True)
    print('[任务] %d 个模型 × %d 轮，模式=%s；严格串行' % (len(cfg['models']),cfg['test']['rounds'],cfg['test']['mode']), flush=True)
    try:
        infos={}
        for model in cfg['models']:
            rec = run_worker(root,cfg,model,'inspect',0)
            if rec['status'] != 'complete':
                overall = rec['status']
                raise RuntimeError('Engine 检查未完成: '+model['name'])
            infos[model['name']] = json.loads((Path(rec['directory'])/'engine_info.json').read_text(encoding='utf-8'))
        compare_infos(infos,cfg)
        write_json(root/'engines.json',infos)
        if args.check:
            overall='checked'
            print('[完成] 配置与 Engine 检查通过；未执行性能测量', flush=True)
            return 0
        modes = ['engine','system'] if cfg['test']['mode']=='both' else [cfg['test']['mode']]
        for mode in modes:
            for round_no in range(1,cfg['test']['rounds']+1):
                for model in cfg['models']:
                    rec=run_worker(root,cfg,model,mode,round_no,infos[model['name']]); jobs.append(rec)
                    generate(root,cfg,jobs,'running')
                    if rec['status'] != 'complete':
                        overall=rec['status']
                        raise RuntimeError('本轮未完成，停止后续测试；已有结果保留')
        overall='complete'
        return 0
    except KeyboardInterrupt:
        overall='interrupted'
        print('[中断] 保存已有结果',flush=True)
        return 130
    except Exception as exc:
        print('[停止] '+str(exc),flush=True)
        write_json(root/'error.json',dict(error=str(exc)))
        return 1
    finally:
        result=generate(root,cfg,jobs,overall)
        print((root/'report.md').read_text(encoding='utf-8'),flush=True)
        print('[结果] '+str(root/'report.md'),flush=True)
        if overall=='complete' and not cfg['output']['save_frame_records']:
            for rec in jobs: (Path(rec['directory'])/'frames.csv').unlink(missing_ok=True)
        sys.stdout=original
        logfile.close()
        lock.close()
        LOCK_FD = None


if __name__=='__main__':
    try: raise SystemExit(main())
    except (ValueError,RuntimeError,FileNotFoundError) as exc:
        print('[错误] '+str(exc),file=sys.stderr)
        raise SystemExit(1)
