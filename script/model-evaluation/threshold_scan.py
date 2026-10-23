#!/usr/bin/env python3
"""Scan confidence 0.05:0.01:0.95 using the existing evaluation pipeline."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
# Integer grid avoids accumulated floating-point additions and includes both ends.
THRESHOLDS = tuple(value / 100 for value in range(5, 96))
CURVE_KEYS = (
    'confidence', 'match_iou', 'TP', 'FP', 'FN', 'precision', 'recall', 'F1',
    'images', 'gt_boxes', 'predicted_boxes', 'no_ball_images',
    'no_ball_false_positive_images', 'no_ball_false_positive_rate', 'fp_boxes_per_image',
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--eval-dir', help='已有完整评估目录，包含 predictions.jsonl、metrics.json 等')
    source.add_argument('--model', help='本地检测权重；先调用 evaluate.py 推理一次，再扫描')
    parser.add_argument('--output', help='新建结果目录；默认 experiments/eval/threshold_scan_<时间>_<后缀>')
    parser.add_argument('--match-iou', type=float, help='TP 匹配 IoU；缓存模式沿用来源配置，新推理默认 0.5')
    parser.add_argument('--formats', default='png', help='png、svg、pdf，可逗号分隔；默认 png')
    parser.add_argument('--dpi', type=int, default=300)
    # Forward these options to evaluate.main only when --model is used.
    parser.add_argument('--data', help='显式指定数据集 YAML')
    parser.add_argument('--dataset-config', help='共享数据集配置，默认 script/config.yaml')
    parser.add_argument('--dataset-version', help='临时选择数据版本，例如 v1')
    parser.add_argument('--metadata', help='显式指定审核 metadata.csv')
    parser.add_argument('--split', choices=('val', 'test', 'train'), help='新推理默认 val')
    parser.add_argument('--class-id', type=int, help='模型足球类别；COCO 参考权重指定 32')
    parser.add_argument('--device', help='例如 0 或 cpu，默认由 Ultralytics 选择')
    parser.add_argument('--imgsz', type=int, help='新推理默认 640')
    parser.add_argument('--batch', type=int, help='新推理默认 4')
    parser.add_argument('--threads', type=int, help='新推理默认 1')
    parser.add_argument('--nms-iou', type=float, help='固定 NMS IoU，新推理默认 0.7；不是扫描项')
    parser.add_argument('--max-det', type=int, help='新推理默认 300')
    parser.add_argument('--limit', type=int, help='只评估前 N 张，报告标记为调试子集')
    args = parser.parse_args(argv)
    if args.match_iou is not None and (not math.isfinite(args.match_iou) or not 0 < args.match_iou <= 1):
        parser.error('match-iou 必须是 (0,1] 内的有限数。')
    if args.dpi <= 0 or not args.formats or any(fmt not in ('png', 'svg', 'pdf') for fmt in args.formats.split(',')):
        parser.error('dpi 必须为正整数，formats 只支持 png、svg、pdf。')
    if args.eval_dir and any(getattr(args, key) is not None for key in INFERENCE_OPTIONS):
        parser.error('--eval-dir 沿用缓存的数据和推理设置，不能额外指定模型推理参数。')
    return args


INFERENCE_OPTIONS = (
    'data', 'dataset_config', 'dataset_version', 'metadata', 'split', 'class_id',
    'device', 'imgsz', 'batch', 'threads', 'nms_iou', 'max_det', 'limit',
)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def load_cached(source):
    """Read a completed snapshot; never silently scan truncated candidate scores."""
    import numpy as np

    status = read_json(source / 'status.json')
    summary = read_json(source / 'metrics.json')
    manifest = read_json(source / 'inputs_manifest.json')
    if status.get('status') != 'complete' or summary.get('status') != 'complete':
        raise ValueError('来源评估尚未完整完成，拒绝扫描。')
    minimum = float(summary['arguments']['min_conf'])
    if not math.isfinite(minimum) or not 0 < minimum <= THRESHOLDS[0]:
        raise ValueError('来源 min_conf 必须 <= 0.05，否则低阈值候选已丢失；请使用 --model 重新推理。')
    selected = manifest['selected']
    records = []
    with (source / 'predictions.jsonl').open(encoding='utf-8') as stream:
        for line_number, line in enumerate(stream, 1):
            row = json.loads(line)
            index = len(records)
            if index >= len(selected) or row['image'] != selected[index]['image']:
                raise ValueError(f'缓存图片顺序与输入清单不一致：第 {line_number} 行。')
            scores = np.asarray(row['scores'], dtype=float)
            boxes = np.asarray(row['boxes'], dtype=float)
            gt = np.asarray(row['gt'], dtype=float)
            if scores.ndim != 1 or len(boxes) != len(scores) or len(gt) != selected[index]['gt_boxes']:
                raise ValueError(f'缓存框/分数数量不一致：{row["image"]}')
            for array in (boxes, gt):
                if array.size and (array.ndim != 2 or array.shape[1] != 4):
                    raise ValueError(f'缓存坐标必须为 N×4：{row["image"]}')
                if not np.isfinite(array).all() or (array.size and np.any(array[:, 2:] <= array[:, :2])):
                    raise ValueError(f'缓存含非法框坐标：{row["image"]}')
            if not np.isfinite(scores).all() or np.any((scores < 0) | (scores > 1)):
                raise ValueError(f'缓存含非法置信度：{row["image"]}')
            records.append(row)
    if not records or len(records) != len(selected) or len(records) != summary['metrics']['images']:
        raise ValueError('预测缓存缺失或图片数量与完整评估记录不同。')
    if sum(len(row['gt']) for row in records) != summary['metrics']['gt_boxes']:
        raise ValueError('预测缓存的 GT 总数与来源评估记录不同。')
    return records, summary, manifest


def save_curves(output, rows, formats, dpi):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    figures = output / 'figures'
    figures.mkdir()
    x = [row['confidence'] for row in rows]
    plots = (
        ('tp_fp_fn_curve', ('TP', 'FP', 'FN'), 'Object count'),
        ('confidence_performance_curve', ('precision', 'recall', 'F1'), 'Score'),
        ('no_ball_fpr_curve', ('no_ball_false_positive_rate',), 'No-ball false-positive image rate'),
    )
    with plt.rc_context({'font.family': 'DejaVu Sans', 'svg.fonttype': 'none', 'pdf.fonttype': 42}):
        for name, keys, ylabel in plots:
            fig, ax = plt.subplots(figsize=(7.2, 4.6))
            try:
                for key in keys:
                    values = [float('nan') if row[key] is None else row[key] for row in rows]
                    ax.plot(x, values, linewidth=1.6, label=key)
                ax.set(xlabel='Confidence threshold', ylabel=ylabel, xlim=(0.05, 0.95))
                ax.set_xticks([value / 100 for value in range(5, 96, 10)])
                ax.set_ylim(bottom=0, top=None if keys[0] == 'TP' else 1.02)
                ax.grid(alpha=0.25)
                ax.legend()
                for fmt in dict.fromkeys(formats.split(',')):
                    fig.savefig(figures / f'{name}.{fmt}', dpi=dpi, bbox_inches='tight')
            finally:
                plt.close(fig)


def main(argv=None):
    args = parse_args(argv)
    output = None
    try:
        from dataset_io import resolve_path, digest

        planned = resolve_path(args.output or (
            'experiments/eval/threshold_scan_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            + '_' + uuid4().hex[:6]), ROOT)
        if planned.exists():
            raise ValueError(f'结果目录已存在，拒绝覆盖：{planned}')
        # The source's manifest and scores are immutable snapshots, not live data.
        if args.eval_dir:
            source = resolve_path(args.eval_dir, ROOT)
            if source in planned.parents:
                raise ValueError('扫描结果须保存到来源评估目录之外。')
            source_paths = [source / name for name in ('status.json', 'metrics.json', 'inputs_manifest.json', 'predictions.jsonl')]
            before = {path.name: digest(path) for path in source_paths}
            records, summary, manifest = load_cached(source)
            data_root = Path(manifest['metadata']).resolve().parent
            if planned == data_root or data_root in planned.parents:
                raise ValueError('扫描结果须保存到原数据集之外。')
        else:
            # Delegate reviewed selection, class mapping, inference and input
            # integrity checks to the project's existing evaluator.
            from evaluate import main as evaluate_main
            # Check its arguments before creating our result directory.
            from evaluate import parse_args as parse_evaluation_args
            evaluation_args = ['--model', args.model, '--min-conf', '0.001', '--conf', '0.05',
                               '--match-iou', str(args.match_iou if args.match_iou is not None else 0.5),
                               '--output', str(planned / 'evaluation'), '--formats', args.formats, '--dpi', str(args.dpi)]
            for key in INFERENCE_OPTIONS:
                if getattr(args, key) is not None:
                    evaluation_args.extend(['--' + key.replace('_', '-'), str(getattr(args, key))])
            parse_evaluation_args(evaluation_args)
            # Let evaluate.py validate the output against the selected dataset
            # before it creates any directory, including this parent.
            if evaluate_main(evaluation_args) != 0:
                raise RuntimeError('基础评估失败；未生成阈值扫描结果，请查看 evaluation/status.json。')
            output = planned
            source = planned / 'evaluation'
            source_paths = [source / name for name in ('status.json', 'metrics.json', 'inputs_manifest.json', 'predictions.jsonl')]
            before = {path.name: digest(path) for path in source_paths}
            records, summary, manifest = load_cached(source)

        from eval_metrics import prepare, operating
        from reporting import write_csv

        match_iou = args.match_iou if args.match_iou is not None else float(summary['arguments']['match_iou'])
        if not math.isfinite(match_iou) or not 0 < match_iou <= 1:
            raise ValueError('来源匹配 IoU 不合法，请用 --match-iou 指定。')
        if output is None:
            planned.mkdir(parents=True, exist_ok=False)
            output = planned
        (output / 'status.json').write_text('{"status":"running"}\n', encoding='utf-8')
        os.environ['MPLCONFIGDIR'] = str(output / '.matplotlib')
        prepared = prepare(records)
        rows = [operating(prepared, confidence, match_iou) for confidence in THRESHOLDS]
        if any(digest(path) != before[path.name] for path in source_paths):
            raise RuntimeError('扫描期间来源评估文件发生变化，拒绝发布结果。')
        tables = output / 'tables'
        tables.mkdir()
        write_csv(tables / 'threshold_scan.csv', [{key: row[key] for key in CURVE_KEYS} for row in rows])
        save_curves(output, rows, args.formats, args.dpi)
        result = dict(
            status='complete', source_evaluation=str(source), model=summary['model'],
            split=summary['split'], partial_split=summary['partial_split'],
            images=len(records), gt_boxes=rows[0]['gt_boxes'], match_iou=match_iou,
            threshold_start=0.05, threshold_step=0.01, threshold_end=0.95, threshold_count=len(rows),
            source_arguments=summary['arguments'], source_files_sha256=before,
            scan_script_sha256=digest(Path(__file__).resolve()),
            matching_script_sha256=digest(Path(__file__).with_name('eval_metrics.py')),
            created_at_utc=datetime.now(timezone.utc).isoformat(), rows=rows,
        )
        (output / 'threshold_scan.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        report = (
            '# 置信度阈值扫描\n\n'
            f'- 来源评估：`{source}`；模型：`{summary["model"]}`。\n'
            f'- 集合：{summary["split"]}；图片 {len(records)} 张；GT {rows[0]["gt_boxes"]} 个；'
            f'是否调试子集：{summary["partial_split"]}。\n'
            f'- 置信度 0.05 至 0.95，步长 0.01，含两端，共 91 个工作点；固定匹配 IoU={match_iou}。\n'
            '- 每个工作点先保留 confidence >= 阈值的预测，再按现有最高 IoU 一对一匹配逻辑重新匹配。\n'
            '- TP 为匹配成功框；FP 为未匹配预测框（含重复框）；FN 为未匹配 GT。\n'
            '- Precision=TP/(TP+FP)，Recall=TP/(TP+FN)，F1=2TP/(2TP+FP+FN)。'
            '零分母口径沿用现有评估工具；未定义值在 JSON 为 null、CSV 为空、图上为断点。\n'
            '- 扫描复用同一次推理后的候选，不改变 NMS、模型头模式或 max_det。'
            '来源 min_conf、类别映射、图像尺寸等完整参数见 threshold_scan.json 和来源 inputs_manifest.json。\n'
            '- 缓存模式使用当时的 GT/预测快照，不重新读取当前模型、图片或标签。\n'
            '- 选择部署阈值请使用 Val；Test 扫描只作描述，不据此选择阈值。\n\n'
            '完整数值：`tables/threshold_scan.csv`、`threshold_scan.json`。\n'
            '曲线：`figures/tp_fp_fn_curve`、`figures/confidence_performance_curve`、`figures/no_ball_fpr_curve`。\n'
        )
        (output / 'REPORT.md').write_text(report, encoding='utf-8')
        (output / 'status.json').write_text('{"status":"complete"}\n', encoding='utf-8')
        print(f'完成 91 个阈值：{output}\n完整表格：{tables / "threshold_scan.csv"}')
        return 0
    except Exception as exc:
        if output is not None:
            (output / 'status.json').write_text(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False) + '\n', encoding='utf-8')
        print(f'阈值扫描失败：{exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
