"""CPU-only report generation; incomplete samples never enter comparisons."""
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    tmp.replace(path)


def percentile(values, q):
    values = sorted(values)
    if not values:
        return None
    p = (len(values) - 1) * q
    lo, hi = int(p), math.ceil(p)
    return values[lo] + (values[hi] - values[lo]) * (p - lo)


def stats(values):
    if not values:
        return {}
    return {'mean': sum(values) / len(values), 'p50': percentile(values, .5),
            'p95': percentile(values, .95), 'min': min(values), 'max': max(values)}


def read_rows(path):
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        rows = []
        for row in csv.DictReader(f):
            try:
                rows.append({k: float(v) for k, v in row.items() if v not in ('', None)})
            except (ValueError, TypeError):
                pass  # A process killed mid-write may leave an incomplete final row.
        return rows


def metrics(rows, mode):
    fields = ['engine_ms', 'execute_wall_ms'] if mode == 'engine' else [
        'detector_ms', 'pipeline_ms', 'read_ms', 'read_ready_to_publish_ms',
        'read_start_to_publish_ms', 'visualization_ms', 'cycle_ms']
    result = {key: stats([r[key] for r in rows if key in r]) for key in fields}
    if mode == 'system' and rows:
        elapsed = rows[-1]['cycle_end'] - rows[0]['cycle_start']
        result['processing_hz'] = len(rows) / elapsed if elapsed > 0 else None
        delta = rows[-1]['publish_end'] - rows[0]['publish_end']
        result['publish_hz'] = (len(rows) - 1) / delta if delta > 0 else None
    return result


def generate(root, config, jobs, overall):
    groups = defaultdict(list)
    rounds = []
    for job in jobs:
        rows = read_rows(Path(job['directory']) / 'frames.csv')
        entry = {k: job[k] for k in ('model', 'mode', 'round', 'status')}
        entry.update(samples=len(rows), metrics=metrics(rows, job['mode']))
        rounds.append(entry)
        if job['status'] == 'complete' and rows:
            groups[(job['model'], job['mode'])].append((rows, entry))
    summary = []
    for (model, mode), runs in groups.items():
        all_rows = [row for rows, _ in runs for row in rows]
        item = dict(model=model, mode=mode, completed_rounds=len(runs), samples=len(all_rows),
                    metrics=metrics(all_rows, 'engine' if mode == 'engine' else 'aggregate'))
        # Separate worker monotonic timestamps have gaps; never pool those gaps into Hz.
        if mode == 'system':
            secs = sum(rows[-1]['cycle_end'] - rows[0]['cycle_start'] for rows, _ in runs)
            pub_secs = sum(rows[-1]['publish_end'] - rows[0]['publish_end'] for rows, _ in runs)
            item['metrics']['processing_hz'] = len(all_rows) / secs if secs > 0 else None
            item['metrics']['publish_hz'] = sum(max(0, len(rows)-1) for rows, _ in runs) / pub_secs if pub_secs > 0 else None
        summary.append(item)
    baseline = config['baseline']
    for item in summary:
        base = next((b for b in summary if b['model'] == baseline and b['mode'] == item['mode']), None)
        if base and base['completed_rounds'] == item['completed_rounds'] == config['test']['rounds']:
            key = 'engine_ms' if item['mode'] == 'engine' else 'read_ready_to_publish_ms'
            a, b = base['metrics'][key]['mean'], item['metrics'][key]['mean']
            item['comparison'] = {key + '_saved': a-b, key + '_reduction_percent': (a-b)/a*100 if a else None}
            if item['mode'] == 'system':
                a, b = base['metrics']['processing_hz'], item['metrics']['processing_hz']
                item['comparison']['processing_hz_gain_percent'] = (b-a)/a*100 if a else None
    result = dict(status=overall, baseline=baseline, summary=summary, rounds=rounds,
                  latency_definition='read_ready_to_publish: BGR stereo images ready -> all ROS publish calls returned; excludes camera capture/buffering and downstream delivery',
                  engine_definition='CUDA events around execute_async_v2, preallocated GPU input/output, excludes H2D/D2H/pre/postprocess; not Ultralytics execute_v2 host overhead')
    write_json(root / 'summary.json', result)
    flat = []
    for item in summary:
        row = {k: item[k] for k in ('model', 'mode', 'completed_rounds', 'samples')}
        for k, v in item['metrics'].items():
            if isinstance(v, dict):
                row.update({k+'_'+s: x for s, x in v.items()})
            else:
                row[k] = v
        row.update(item.get('comparison', {}))
        flat.append(row)
    fields = list(dict.fromkeys(k for r in flat for k in r)) or ['model', 'mode']
    with (root/'summary.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fields); w.writeheader(); w.writerows(flat)
    lines = ['# 模型性能测试', '', '状态：' + overall, '',
             'Engine 为 ms/batch；只汇总完整轮次。变化率仅在双方完成所有计划轮次后提供。',
             '系统延迟是“读取完成到发布调用返回”，不包含相机曝光/缓存或下游接收。',
             '系统 Hz 包含 ROS、Viser 和调度等待；不能用 1000/Engine耗时代替。', '',
             '| 模型 | 模式 | 完成轮数 | 样本 | 耗时均值 ms | P95 ms | 处理 Hz | 发布 Hz |',
             '|---|---|---:|---:|---:|---:|---:|---:|']
    def fmt(x): return '-' if x is None else '%.3f' % x
    for item in summary:
        m = item['metrics']; key = 'engine_ms' if item['mode']=='engine' else 'read_ready_to_publish_ms'
        lines.append('| %s | %s | %d | %d | %s | %s | %s | %s |' % (
            item['model'], item['mode'], item['completed_rounds'], item['samples'],
            fmt(m[key].get('mean')), fmt(m[key].get('p95')), fmt(m.get('processing_hz')), fmt(m.get('publish_hz'))))
    lines += ['', '## 相对基线 ' + baseline, '']
    for item in summary:
        if 'comparison' in item:
            lines.append('- %s / %s：%s' % (item['model'], item['mode'], ', '.join(k+'='+fmt(v) for k,v in item['comparison'].items())))
    lines += ['', '各轮数据见 summary.json；配置见 config_resolved.yaml；逐帧数据和工作进程日志在各轮目录。',
              '系统默认 ROS_DOMAIN_ID=87；Viser 客户端连接数、场景和背景负载应保持一致。']
    (root/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return result
