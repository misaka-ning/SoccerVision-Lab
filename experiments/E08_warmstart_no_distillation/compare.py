"""Three-way Val comparison. No metrics copied from prose; missing evidence is not_run."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

METRICS = ('mAP50', 'mAP50_95', 'precision', 'recall', 'small_recall', 'occluded_recall',
           'no_ball_false_positive_rate')
POLICY = dict(split='val', class_id=0, imgsz=640, batch=4, threads=1, min_conf=.001,
              conf=.45, match_iou=.5, nms_iou=.7, max_det=300)


def extract(result):
    values = {k: result['metrics'][k] for k in METRICS if k not in ('small_recall', 'occluded_recall')}
    values.update(small_recall=result['scene_metrics']['Small']['recall'],
                  occluded_recall=result['scene_metrics']['Occluded']['recall'])
    return values


def validate_evaluation(e, directory, run, checkpoint, device):
    """Use the original shared completion checks, targeting the archived evaluator."""
    from unittest.mock import patch
    record = e.load(run/'run_record.json')
    # E05's reader checks both manifest and result options, complete Val membership,
    # checkpoint/data/code hashes, prediction order, FP32 and one-to-many output.
    # Only its source-code directory is redirected to the run's immutable snapshot.
    original_options = e.base.evaluation_options
    def options(r, c, d, conf):
        result = original_options(r, c, d, conf)
        result['metadata'] = str(Path(record['data_root'])/'metadata.csv')
        return result
    with patch.object(e.base, 'DATA', Path(record['data_root'])), \
            patch.object(e.base, 'evaluation_options', options):
        # completed_evaluation expects ROOT/script/model-evaluation. Use a tiny
        # read-only path adapter instead of changing global shared implementation.
        class SourceRoot:
            def __truediv__(self, value):
                if value == 'script/model-evaluation':
                    return run/'evaluation_code'
                return e.ROOT/value
        with patch.object(e.base, 'ROOT', SourceRoot()):
            result = e.base.completed_evaluation(directory, run, checkpoint, device, .45)
    if (result['metrics']['gt_boxes'] != 855 or result['metrics']['no_ball_images'] != 410
            or result['metrics']['confidence'] != .45 or result['metrics']['match_iou'] != .5):
        raise ValueError('GT, negative-image denominator or operating point changed')
    # Recompute cached summaries using the same shared metric module. A modified
    # metrics.json or missing Small/Occluded subgroup must never pass as evidence.
    metrics = e.base.module('e08_validation_metrics', run/'evaluation_code/eval_metrics.py')
    rows = [json.loads(line) for line in (directory/'predictions.jsonl').read_text().splitlines() if line.strip()]
    io = e.base.module('e08_comparison_dataset', run/'evaluation_code/dataset_io.py')
    selection = io.select(run/'dataset.val-evaluation.yaml', 'val', Path(record['data_root'])/'metadata.csv')
    if selection.skipped or len(selection.samples) != len(rows):
        raise ValueError('cached predictions no longer cover the full Val selection')
    import numpy as np
    for row, sample in zip(rows, selection.samples):
        if (row['gt'] != sample.gt or row['flags'] != sample.flags
                or row['width'] != sample.width or row['height'] != sample.height):
            raise ValueError('prediction GT/scenes/dimensions differ from frozen Val')
        boxes = np.asarray(row['boxes'], dtype=float).reshape(-1, 4)
        scores = np.asarray(row['scores'], dtype=float)
        if (len(scores) != len(boxes) or len(scores) > 300 or not np.isfinite(boxes).all()
                or not np.isfinite(scores).all() or np.any((scores < .001) | (scores > 1))
                or np.any(boxes[:, 2:] < boxes[:, :2]) or np.any(boxes[:, :2] < -1e-3)
                or np.any(boxes[:, 2:] > np.array([sample.width, sample.height])+1e-3)):
            raise ValueError('invalid cached predictions')
    prepared = metrics.prepare(rows)
    for scene, subset in metrics.groups(prepared).items():
        actual, _ = metrics.summarize(subset, .45, .5)
        published = result['scene_metrics'][scene]
        for key in ('mAP50', 'mAP50_95', 'precision', 'recall', 'TP', 'FP', 'FN',
                    'no_ball_images', 'no_ball_false_positive_images', 'no_ball_false_positive_rate'):
            if actual[key] is None or published[key] is None:
                same = actual[key] is published[key]
            else:
                same = abs(actual[key]-published[key]) <= 1e-12
            if not same:
                raise ValueError(f'cached metric differs from predictions: {scene}/{key}')
    if result['metrics'] != result['scene_metrics']['All']:
        raise ValueError('overall metrics differ from All scene')
    return result


def available_checkpoint(e, source_run, expected=None):
    path = source_run/'run_record.json'
    if not path.is_file():
        return None, 'source run record unavailable'
    record = e.load(path)
    if record.get('status') != 'trained':
        return None, 'formal training not completed'
    checkpoint = source_run/'train/weights/best.pt'
    if not checkpoint.is_file():
        return None, 'best.pt unavailable'
    digest = e.sha(checkpoint)
    if digest != record['training']['checkpoints']['best']['sha256'] or (expected and digest != expected):
        raise ValueError(f'checkpoint source mismatch: {checkpoint}')
    return checkpoint, record


def render(summary):
    lines = ['# E05 / E08 NoKD / E07 WarmKD', '',
             '完整开发 Val；AP 候选 conf≥0.001，工作点 conf=0.45，匹配 IoU=0.5；'
             'NMS IoU=0.7，max_det=300，640，FP32，one-to-many，batch4。', '',
             '|模型|状态|AP50|AP50–95|Precision|Recall|Small Recall|Occluded Recall|无球FPR|',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for name, row in summary['models'].items():
        values = row['metrics']
        text = ['not_run' if values[k] == 'not_run' else ('undefined' if values[k] is None else f'{100*values[k]:.3f}%') for k in METRICS]
        lines.append('|'+name+'|'+row['status']+'|'+'|'.join(text)+'|')
    lines += ['', '|模型|本阶段轮数|最佳CSV轮次|上限 / patience|停止原因|耗时秒|实际更新次数|前置E05训练轮数 / 起点轮次|',
              '|---|---:|---:|---|---|---:|---:|---|']
    for name, row in summary['models'].items():
        b = row['budget']
        vals = [b.get(k, 'not_run') for k in ('epochs_completed', 'best_csv_map_epoch')]
        vals += [f"{b['max_epochs']} / {b['patience']}", b.get('stop_reason', 'not_run'),
                 b.get('elapsed_seconds', 'not_run'), b.get('optimizer_updates', 'not_run'),
                 '0 / 0' if name == 'E05' else '73 / 43']
        lines.append('|'+name+'|'+'|'.join(map(str, vals))+'|')
    lines += ['', '无球FPR = 至少一个过工作阈值预测的无球图数 / 无球图数；不是FP框数/总图数。',
              'Small/Occluded 使用冻结metadata场景标记、以各场景GT框数为召回分母；场景有交集。',
              'E07−E08是相同起点、训练配方和早停规则下的KD对照；E08−E05反映额外训练。',
              '早停可能产生不同实际预算；不声称固定更新次数因果效果或单seed统计显著性。',
              'E05前置训练完整花费73轮，但best.pt只经历43轮；不得把二者混为一谈。',
              '缺少原始结果的not_run只表示本次未核验，不否认历史报告。没有Test或部署结论。', '',
              '差值（百分点）：`'+json.dumps(summary['metric_deltas_pp'], ensure_ascii=False)+'`',
              '预算差（E07−E08）：`'+json.dumps(summary['budget_delta'], ensure_ascii=False)+'`']
    return '\n'.join(lines)+'\n'


def compare(e, run=None, evaluate=False, device='0'):
    if evaluate and run is None:
        raise ValueError('--evaluate requires a prepared --run')
    if run:
        e.verify(run)
        record = e.load(run/'run_record.json')
        sources = dict(E05=Path(record['e05_run']), E08=run, E07=Path(record['e07_run']))
    else:
        sources = dict(E05=e.reference.PARENT, E08=None, E07=e.E07_RUN)
    summary = dict(schema_version=1, policy={**POLICY, 'device': device}, models={},
                   metrics_source='shared evaluator, complete raw evidence required',
                   test_images_or_labels_opened=False, deployment='not_run')
    if run:
        e.runtime(run)
    if evaluate:
        if device != 'cpu':
            import torch
            e.reference.gpu_ready(torch)
    # Each invocation owns a new output directory. A failed evaluation is preserved;
    # subsequent invocations never treat its partial files as a completed run.
    output = (run or e.HERE/'runs')/('comparison_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    for name, source in sources.items():
        row = dict(status='not_run', metrics={k: 'not_run' for k in METRICS},
                   budget=dict(status='not_run', max_epochs=100, patience=30))
        summary['models'][name] = row
        if source is None:
            row['reason'] = 'control not prepared'
            continue
        checkpoint, source_record = available_checkpoint(e, source, e.STUDENT_SHA if name == 'E05' else None)
        if checkpoint is None:
            row['reason'] = source_record
            continue
        row['budget'] = e.control.csv_budget(source, source_record)
        if (source/'training_budget.json').is_file():
            audited = e.load(source/'training_budget.json')
            if audited['epochs_completed'] != row['budget']['epochs_completed']:
                raise ValueError('budget disagrees with actual CSV rows')
            row['budget'].update(audited)
        row['checkpoint_sha256'] = e.sha(checkpoint)
        row['source_run'] = str(source)
        row['budget_sources'] = {str(p): e.sha(p) for p in
            (source/'run_record.json', source/'train/results.csv', source/'training_budget.json') if p.is_file()}
        directory = None
        result = None
        if run:
            for cached in sorted(run.glob('comparison_*/'+name), reverse=True):
                if cached == output/name or not (cached/'status.json').is_file():
                    continue
                if e.load(cached/'status.json').get('status') != 'complete':
                    continue  # preserve failed/partial output, never promote it
                # Different devices are separate comparisons, not reusable data.
                if e.load(cached/'metrics.json')['arguments'].get('device') != device:
                    continue
                result = validate_evaluation(e, cached, run, checkpoint, device)
                directory = cached
                break
        if result is None and not evaluate:
            row['reason'] = 'uniform Val not run; use compare --evaluate'
            continue
        if result is None:
            directory = output/name
            args = dict(POLICY, model=str(checkpoint), data=str(run/'dataset.val-evaluation.yaml'),
                        metadata=str(Path(record['data_root'])/'metadata.csv'), device=device, output=str(directory))
            command = [sys.executable, str(run/'evaluation_code/evaluate.py')]
            for key, value in args.items():
                command += ['--'+key.replace('_', '-'), str(value)]
            with e.gpu_lock():
                if device != 'cpu':
                    e.reference.gpu_ready(torch)
                subprocess.run(command, check=True)
            result = validate_evaluation(e, directory, run, checkpoint, device)
        if 'val_denominators' in summary:
            current_denominators = {k: result['scene_metrics'][k]['gt_boxes'] for k in ('All', 'Small', 'Occluded')}
            if current_denominators != summary['val_denominators']:
                raise ValueError('scene denominators differ across models')
        summary['val_denominators'] = {k: result['scene_metrics'][k]['gt_boxes'] for k in ('All', 'Small', 'Occluded')}
        if 'evaluation_versions' in summary and result['versions'] != summary['evaluation_versions']:
            raise ValueError('evaluation dependency versions differ across models')
        summary['evaluation_versions'] = result['versions']
        row.update(status='complete', metrics=extract(result), raw_evaluation=str(directory),
                   evidence_sha256={p: e.sha(directory/p) for p in ('metrics.json', 'inputs_manifest.json', 'predictions.jsonl', 'status.json')},
                   no_ball=dict(false_positive_images=result['metrics']['no_ball_false_positive_images'],
                                images=result['metrics']['no_ball_images']))
        if e.sha(checkpoint) != row['checkpoint_sha256']:
            raise ValueError('checkpoint changed during comparison')
    summary['metric_deltas_pp'] = {}
    for left, right in [('E08', 'E05'), ('E07', 'E08'), ('E07', 'E05')]:
        a, b = summary['models'][left]['metrics'], summary['models'][right]['metrics']
        summary['metric_deltas_pp'][left+'-'+right] = {k: 100*(a[k]-b[k]) if isinstance(a[k], (float, int))
            and isinstance(b[k], (float, int)) else 'not_run' for k in METRICS}
    a, b = summary['models']['E07']['budget'], summary['models']['E08']['budget']
    summary['budget_delta'] = {k: a[k]-b[k] if isinstance(a.get(k), (int, float)) and isinstance(b.get(k), (int, float))
                              else 'not_run' for k in ('epochs_completed', 'elapsed_seconds', 'optimizer_updates')}
    if run:
        e.verify(run)
    for name, row in summary['models'].items():
        for path, digest in row.get('budget_sources', {}).items():
            if e.sha(path) != digest:
                raise ValueError('training budget source changed during comparison')
        if 'checkpoint_sha256' in row and e.sha(sources[name]/'train/weights/best.pt') != row['checkpoint_sha256']:
            raise ValueError('source checkpoint changed before publishing comparison')
    e.dump(output/'comparison.json', summary)
    (output/'COMPARISON.md').write_text(render(summary))
    with (output/'comparison.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['model', 'status', *METRICS])
        writer.writeheader()
        for name, row in summary['models'].items():
            writer.writerow(dict(model=name, status=row['status'], **row['metrics']))
    print(output/'COMPARISON.md')
    return output
