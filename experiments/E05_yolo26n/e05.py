#!/usr/bin/env python3
"""E05 orchestration; shared trainer and Val metrics remain the source of truth."""
from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from uuid import uuid4

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / 'datasets/v1'
PARENT = ROOT / 'experiments/E01_baseline/runs/20261019T092432Z_s42_853c4a'
BASELINE = ROOT / 'models_list/E01_baseline.pt'
BASELINE_SHA = '285c198aff043fe7e7486515dbdc1a2cc02db5daf9a0f55f8ce3c6cabf2743ac'
PRETRAINED = HERE / 'assets/yolo26n.pt'
VERSION = '8.4.173'
COUNTS = {'train': 4346, 'val': 1223}


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def dump(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False) + '\n')
    temp.replace(path)


def load(path):
    return json.loads(Path(path).read_text())


def module(name, path):
    sys.path.insert(0, str(Path(path).parent))
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def runtime(run):
    os.environ.update(YOLO_OFFLINE='true', YOLO_AUTOINSTALL='false',
                      YOLO_CONFIG_DIR=str(run/'runtime/yolo'), MPLCONFIGDIR=str(run/'runtime/matplotlib'),
                      CUBLAS_WORKSPACE_CONFIG=':4096:8', OMP_NUM_THREADS='4', MKL_NUM_THREADS='4',
                      OPENBLAS_NUM_THREADS='4')
    import torch
    import ultralytics
    if ultralytics.__version__ != VERSION or not torch.__version__.startswith('2.9.1'):
        raise ValueError(f'需要 E01 兼容环境：Ultralytics {VERSION} / Torch 2.9.1；禁止自动升级')
    # Keep the official AMP check local too; its probe model is not a training initialization.
    ultralytics.settings.update({'weights_dir':str(HERE/'assets'), 'sync':False})
    import ultralytics.utils
    ultralytics.utils.WEIGHTS_DIR = HERE/'assets'
    torch.set_num_threads(4)
    return torch


def run_path(value=None):
    run = Path(value).expanduser().resolve() if value else Path(load(HERE/'LOCAL_READY.json')['run'])
    if run.parent != (HERE/'runs').resolve() or not (run/'run_record.json').is_file():
        raise ValueError('run 必须是本实验 runs 下的已准备目录')
    return run


def verify(run):
    checked = 0
    revisions = []
    for filename in ('protected_inputs.json', 'train_val_expected_hashes.json'):
        for path, expected in load(run/filename).items():
            actual = sha(path)
            if actual != expected:
                revision = post_training_source_revision(run, Path(path), expected, actual) if filename == 'protected_inputs.json' else None
                if revision is None:
                    raise ValueError(f'受保护输入变化：{path}；不要继续此 run，调查后新建运行')
                revisions.append(str(revision))
            checked += 1
    return dict(utc=now(), checked_files=checked, unchanged=not revisions, data_and_model_files_unchanged=True,
                post_training_source_revisions=revisions, test_images_or_labels_opened=False)


def post_training_source_revision(run, path, original, current):
    """Allow only an explicitly archived orchestration repair after training.

    The original protected manifest and executed source stay immutable. No model,
    data, config, shared metric code or still-trainable run can use this exception.
    """
    if path != HERE/'e05.py' or load(run/'run_record.json').get('status') != 'trained':
        return None
    snapshot = run/'source'/path.relative_to(ROOT)
    if not snapshot.is_file() or sha(snapshot) != original:
        return None
    for entry in sorted((run/'post_training_revisions').glob('*/manifest.json')):
        revision = load(entry)
        if (revision.get('run_id') == run.name and revision.get('source') == str(path)
                and revision.get('original_sha256') == original and revision.get('revised_sha256') == current
                and revision.get('protected_inputs_sha256') == sha(run/'protected_inputs.json')
                and sha(entry.parent/'e05.revised.py') == current
                and sha(entry.parent/'source.diff') == revision.get('patch_sha256')):
            return entry
    return None


def members(rows, split, names):
    selected = [r for r in rows if r['usage'] == split]
    selected_names = [r['filename'] for r in selected]
    if (len(selected) != COUNTS[split] or len(set(selected_names)) != len(selected_names)
            or len(names) != len(selected_names) or set(names) != set(selected_names)):
        raise ValueError(f'E01 {split} 成员/数量不一致')
    if any(Path(n).name != n or n in ('.', '..') for n in selected_names):
        raise ValueError('manifest filename 不能包含目录')
    return selected


def dataset_view(run):
    import yaml
    old = load(PARENT/'input_fingerprints.json')
    protected = [DATA/'manifest.csv', DATA/'metadata.csv', DATA/'lists/train.txt', DATA/'lists/val.txt']
    for path in protected:
        if sha(path) != old[str(path)]:
            raise ValueError(f'E01 冻结数据索引变化：{path}')
    with (DATA/'manifest.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    view = run/'runtime/dataset'
    for split in COUNTS:
        names = [Path(line).name for line in (DATA/f'lists/{split}.txt').read_text(encoding='utf-8-sig').splitlines() if line.strip()]
        selected = members(rows, split, names)
        actual = {p.name for p in (DATA/'images'/split).iterdir() if p.is_file()}
        if actual != set(names):
            raise ValueError(f'{split} 实际目录成员变化')
        for kind in ('images', 'labels'):
            dest = view/kind/split
            dest.mkdir(parents=True)
            for row in selected:
                source = DATA/kind/split/(row['filename'] if kind == 'images' else Path(row['filename']).with_suffix('.txt').name)
                if old[str(source)] != row['image_sha256' if kind == 'images' else 'label_sha256']:
                    raise ValueError(f'E01 与 manifest hash 不一致：{source}')
                (dest/source.name).symlink_to(source)
    config = dict(path=str(view), train='images/train', val='images/val', nc=1, names={0:'football'}, channels=3)
    (run/'dataset.train-val.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
    config['path'] = str(DATA)
    (run/'dataset.val-evaluation.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
    io = module('e05_dataset_io', ROOT/'script/model-evaluation/dataset_io.py')
    fingerprints, counts = {}, {}
    for split, expected in COUNTS.items():
        selection = io.select(run/'dataset.val-evaluation.yaml', split, DATA/'metadata.csv')
        if selection.skipped or len(selection.samples) != expected:
            raise ValueError(f'{split} 不是完整的 E01 已审核集合')
        for sample in selection.samples:
            # Ultralytics can repair truncated JPEGs in place. Reject them first.
            if sample.image.suffix.lower() in ('.jpg', '.jpeg'):
                with sample.image.open('rb') as stream:
                    stream.seek(-2, 2)
                    if stream.read() != b'\xff\xd9':
                        raise ValueError(f'拒绝可能触发原图自动修复的 JPEG：{sample.image}')
            for path, digest in ((sample.image, sample.hashes['image_sha256']), (sample.label, sample.hashes['label_sha256'])):
                if digest != old[str(path)]:
                    raise ValueError(f'原始图片/标注与 E01 不一致：{path}')
                fingerprints[str(path)] = digest
        counts[split] = dict(images=len(selection.samples), boxes=sum(len(s.gt) for s in selection.samples),
                             scenes={k:sum(s.flags[k] for s in selection.samples) for k in io.SCENES})
    dump(run/'train_val_expected_hashes.json', fingerprints)
    return counts


def check_nano(model, nc):
    head = model.model[-1]
    if model.yaml.get('scale') != 'n' or head.nc != nc or head.reg_max != 1:
        raise ValueError('需要官方 YOLO26n / reg_max=1，不允许把 s 权重改名为 n')
    if model.yaml.get('end2end') is not True or not hasattr(head, 'one2one_cv3'):
        raise ValueError('需要保留官方双分支训练头')


def recipe(run):
    import yaml
    reference = yaml.safe_load((PARENT/'train.requested.yaml').read_text())
    config = yaml.safe_load((HERE/'train.template.yaml').read_text())
    variable = {'model', 'data', 'project'}
    if {k:v for k,v in config.items() if k not in variable} != {k:v for k,v in reference.items() if k not in variable}:
        raise ValueError('E05 与 E01 训练配方漂移；更改超参数必须另行设计实验')
    config.update(model=str(run/'init.pt'), data=str(run/'dataset.train-val.yaml'), project=str(run))
    return config


def prepare():
    import yaml
    if sha(BASELINE) != BASELINE_SHA or sha(PRETRAINED) != load(HERE/'PRETRAINED.json')['sha256']:
        raise ValueError('E01 基线或官方初始化权重 hash 不符')
    run = HERE/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_s42_' + uuid4().hex[:6])
    run.mkdir(parents=True, exist_ok=False)
    record = dict(experiment_id=HERE.name, run_id=run.name, status='preparing', created_utc=now(),
                  training_started=False, parent_run_id=PARENT.name, training={}, test_accessed=False)
    dump(run/'run_record.json', record)
    try:
        torch = runtime(run)
        from ultralytics import YOLO
        from ultralytics.nn.tasks import DetectionModel
        from ultralytics.utils.torch_utils import init_seeds
        init_seeds(42, deterministic=True)
        source = YOLO(str(PRETRAINED), task='detect').model.cpu().float().eval()
        check_nano(source, 80)
        cfg = deepcopy(source.yaml)
        cfg.pop('yaml_file', None)
        cfg['nc'] = 1
        target = DetectionModel(deepcopy(cfg), ch=3, nc=1, verbose=False).float().eval()
        target.names = {0:'football'}
        target.load(source, verbose=False)
        check_nano(target, 1)
        old, new = source.state_dict(), target.state_dict()
        matched, reset = [], []
        for key, value in new.items():
            if key in old and value.shape == old[key].shape:
                if not torch.equal(value, old[key]):
                    raise ValueError(f'兼容权重未精确迁移：{key}')
                matched.append(dict(key=key, shape=list(value.shape)))
            else:
                reset.append(dict(key=key, old_shape=list(old[key].shape) if key in old else None, new_shape=list(value.shape)))
        if not reset or any('cv3' not in item['key'] for item in reset):
            raise ValueError('非预期的分类头之外的重置')
        (run/'architecture.yaml').write_text(yaml.safe_dump(cfg, sort_keys=False))
        # Save FP32 explicitly: YOLO.save() would quantize newly initialized weights to FP16.
        target.args = dict(task='detect', model=str(run/'architecture.yaml'), imgsz=640, nms=True)
        torch.save(dict(model=deepcopy(target), ema=None, optimizer=None, epoch=-1, train_args=target.args,
                        version=VERSION, date=now()), run/'init.pt')
        loaded = YOLO(str(run/'init.pt'), task='detect').model.float()
        rebuilt = DetectionModel(deepcopy(cfg), ch=3, nc=1, verbose=False).float()
        rebuilt.names = {0:'football'}
        rebuilt.load(loaded, verbose=False)
        for key, value in new.items():
            if not torch.equal(value, loaded.state_dict()[key]) or not torch.equal(value, rebuilt.state_dict()[key]):
                raise ValueError(f'checkpoint/官方重建丢失初始化：{key}')
        target.end2end = False
        with torch.inference_mode():
            output = target(torch.rand(2, 3, 640, 640))
        raw = output[0] if isinstance(output, tuple) else output
        if list(raw.shape) != [2,5,8400] or not torch.isfinite(raw).all():
            raise ValueError('one-to-many 固定 batch2 输出契约失败')
        dump(run/'transfer.json', dict(strategy='official nano pretrained -> official nc1 DetectionModel.load',
             source_sha256=sha(PRETRAINED), source_nc=80, target_nc=1, matched=matched, reinitialized=reset,
             source_parameters=sum(p.numel() for p in source.parameters()), target_parameters=sum(p.numel() for p in target.parameters()),
             compatible_values_exact=True, checkpoint_roundtrip_exact=True, official_rebuild_exact=True,
             raw_shape=list(raw.shape), training_branches='one2many + one2one', deployment_branch='one2many + external NMS'))
        counts = dataset_view(run)
        config = recipe(run)
        (run/'train.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        shared = module('e05_shared_train', ROOT/'script/model-training/train.py')
        shared.build_plan(shared.parse_args(['--config', str(run/'train.yaml')]))
        sources = [Path(__file__), HERE/'export_onnx.py', HERE/'build_engine_robot.py', HERE/'start_training.sh', HERE/'status.sh', HERE/'train.template.yaml',
                   ROOT/'script/model-training/train.py', ROOT/'script/common/dataset_config.py']
        sources += sorted((ROOT/'script/model-evaluation').glob('*.py'))
        protected = sources + [PRETRAINED, BASELINE, HERE/'PRETRAINED.json', PARENT/'train.requested.yaml',
                    PARENT/'input_fingerprints.json', DATA/'manifest.csv', DATA/'metadata.csv', DATA/'lists/train.txt', DATA/'lists/val.txt',
                    run/'init.pt', run/'architecture.yaml', run/'train.yaml', run/'dataset.train-val.yaml',
                    run/'dataset.val-evaluation.yaml', run/'train_val_expected_hashes.json']
        dump(run/'protected_inputs.json', {str(p):sha(p) for p in protected})
        snapshot = run/'source'
        for path in sources:
            dest = snapshot/path.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        record.update(status='prepared', data=counts, training_recipe_ref=str(PARENT/'train.requested.yaml'),
                      baseline_sha256=BASELINE_SHA, initialization=load(HERE/'PRETRAINED.json'),
                      comparison_limit='E01 s already football-trained initialization; E05 n official general pretraining. Not a pure architecture-only comparison.',
                      source_commit=subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip())
        (run/'source/git_status.txt').write_text(subprocess.check_output(['git','status','--short'], cwd=ROOT, text=True))
        dump(run/'prepare_environment.json', dict(python=sys.version, executable=sys.executable, platform=platform.platform(), torch=torch.__version__, ultralytics=VERSION))
        dump(run/'precheck.json', dict(status='passed', optimizer_steps=0, training_started=False, data=counts,
             all_train_val_contents_match_E01=True, test_images_or_labels_opened=False, cpu_raw_shape=list(raw.shape), dtype=str(raw.dtype)))
        dump(run/'run_record.json', record)
        dump(run/'input_integrity.prepared.json', verify(run))
        dump(HERE/'LOCAL_READY.json', dict(run=str(run), status='prepared', utc=now()))
        print(f'PREPARED: {run}', flush=True)
    except BaseException as exc:
        record.update(status='prepare_failed', error=repr(exc))
        dump(run/'run_record.json', record)
        raise


def train(run, resume=False, dry_run=False):
    # Hold a process-wide lock through hash checks, training and finalization.
    with (HERE/'.training.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('另一个 E05 训练正在运行；不要重复启动') from None
        torch = runtime(run)
        dump(run/'input_integrity.before_training.json', verify(run))
        record = load(run/'run_record.json')
        out = run/'train'
        if not resume and out.exists():
            raise FileExistsError(f'{out} 已存在；中断后用 --resume，不自动覆盖/新建 train2')
        if record['status'] not in ('prepared', 'training_failed', 'training'):
            raise ValueError(f"当前状态不能训练：{record['status']}")
        shared = module('e05_shared_train', ROOT/'script/model-training/train.py')
        if resume:
            source = out/'weights/resume-last.pt'
            ckpt = torch.load(source, map_location='cpu', weights_only=False)
            if ckpt.get('optimizer') is None or ckpt.get('epoch', -1) < 0:
                raise ValueError('恢复 checkpoint 没有 optimizer/epoch，不能冒充续训')
            _, args = shared.build_plan(shared.parse_args(['--resume', str(source), '--device', '0']))
        else:
            source, args = shared.build_plan(shared.parse_args(['--config', str(run/'train.yaml')]))
        if dry_run:
            print(json.dumps(dict(model=str(source), arguments=args, protected_inputs='passed', training_started=False), ensure_ascii=False, indent=2))
            return
        if not torch.cuda.is_available():
            raise ValueError('CUDA 不可用；尚未创建训练输出，检查 GPU 运行环境')
        from ultralytics import YOLO
        model = YOLO(str(source), task='detect')
        check_nano(model.model, 1)
        dump(run/'training_environment.json', dict(python=sys.version, executable=sys.executable, torch=torch.__version__,
             ultralytics=VERSION, cuda=torch.version.cuda, gpu=torch.cuda.get_device_name(0),
             nvidia_smi=subprocess.check_output(['nvidia-smi'], text=True)))

        def ready(t):
            check_nano(t.model, 1)
            if (t.save_dir.resolve() != out.resolve() or t.model.names != {0:'football'} or len(t.train_loader.dataset) != 4346
                    or len(t.test_loader.dataset) != 1223 or t.data.get('test') or t.args.nms is not True):
                raise ValueError('正式训练数据、分支、类别或保存目录与预检查不一致')
            if not resume:
                initial = YOLO(str(run/'init.pt')).model.float().state_dict()
                if any(not torch.equal(v, t.model.state_dict()[k].cpu()) for k,v in initial.items()):
                    raise ValueError('首次梯度更新之前，正式训练初始化已变化')
            dump(run/'train.effective.json', vars(t.args))
            dump(run/'optimizer.effective.json', dict(name=type(t.optimizer).__name__, accumulate=t.accumulate,
                 amp=bool(t.amp), groups=[{k:v for k,v in g.items() if k != 'params'} for g in t.optimizer.param_groups]))

        def saved(t):
            if t.last.exists():
                temporary = t.wdir/'resume-last.pt.tmp'
                shutil.copy2(t.last, temporary)
                temporary.replace(t.wdir/'resume-last.pt')

        def epoch(t):
            dump(run/'progress.json', dict(utc=now(), epoch=t.epoch+1, epochs=t.epochs,
                 metrics=getattr(t, 'metrics', {}), best_fitness=float(t.best_fitness) if t.best_fitness is not None else None))

        model.add_callback('on_pretrain_routine_end', ready)
        model.add_callback('on_model_save', saved)
        model.add_callback('on_fit_epoch_end', epoch)
        if resume:
            record['training'].setdefault('resume_events', []).append(dict(utc=now(), sha256=sha(source)))
        record.update(status='training', training_started=True, pid=os.getpid())
        dump(run/'run_record.json', record)
        start = time.perf_counter()
        try:
            model.train(**args)
            dump(run/'input_integrity.after_training.json', verify(run))
            record.update(status='trained', completed_utc=now())
            record['training'].update(elapsed_seconds=time.perf_counter()-start,
                checkpoints={k:dict(path=str(out/f'weights/{k}.pt'), sha256=sha(out/f'weights/{k}.pt')) for k in ('best', 'last')})
        except BaseException as exc:
            record.update(status='training_failed', error=repr(exc))
            raise
        finally:
            dump(run/'run_record.json', record)
        print('训练已完成；独立 Val 与 TensorRT 实机验收尚未执行。', flush=True)


def evaluation_options(run, checkpoint, device, conf):
    return dict(model=str(checkpoint), data=str(run/'dataset.val-evaluation.yaml'), metadata=str(DATA/'metadata.csv'),
                split='val', class_id=0, imgsz=640, batch=4, threads=1, device=device,
                min_conf=.001, conf=conf, match_iou=.5, nms_iou=.7, max_det=300)


def completed_evaluation(directory, run, checkpoint, device, conf):
    """Read the shared evaluator's actual metrics.json contract, checking provenance."""
    status = load(directory/'status.json')
    result = load(directory/'metrics.json')
    manifest = load(directory/'inputs_manifest.json')
    if (status.get('status') != 'complete' or result.get('status') != 'complete'
            or status.get('input_files_verified_unchanged') is not True or result.get('input_files_verified_unchanged') is not True
            or result.get('split') != 'val' or result.get('partial_split') is not False
            or result.get('available_before_limit') != COUNTS['val'] or result.get('skipped_images') != 0
            or result.get('model_class_id') != 0 or result['metrics']['images'] != COUNTS['val']):
        raise ValueError(f'既有结果不是已完成的完整 Val：{directory}；保留原目录，不能直接复用')
    expected = evaluation_options(run, checkpoint, device, conf)
    for source in (result['arguments'], manifest['arguments']):
        if source.get('limit') is not None or any(source.get(k) != v for k,v in expected.items()):
            raise ValueError(f'既有结果参数与本次不一致：{directory}')
    if (result['model'] != str(checkpoint) or manifest['model_sha256'] != sha(checkpoint)
            or manifest['dataset_yaml_sha256'] != sha(run/'dataset.val-evaluation.yaml')
            or manifest['metadata_sha256'] != sha(DATA/'metadata.csv')
            or manifest['evaluation_code_sha256'] != {p.name:sha(p) for p in (ROOT/'script/model-evaluation').glob('*.py')}):
        raise ValueError(f'既有结果模型、数据配置或评估代码 hash 不一致：{directory}')
    backend = result['runtime']
    if backend.get('backend_end2end') is not False or backend.get('backend_fp16') is not False or backend.get('actual_input_shape') != [640,640]:
        raise ValueError('评估须使用 FP32、one-to-many、640 输入')
    frozen = load(run/'train_val_expected_hashes.json')
    val_root = DATA/'images/val'
    expected_images = {p:d for p,d in frozen.items() if Path(p).parent == val_root}
    selected = manifest['selected']
    if (len(selected) != COUNTS['val'] or len(expected_images) != COUNTS['val']
            or {s['image']:s['image_sha256'] for s in selected} != expected_images
            or any(s['label_sha256'] != frozen.get(s['label']) for s in selected)):
        raise ValueError('既有结果的 Val 成员/内容 hash 不一致')
    with (directory/'predictions.jsonl').open() as stream:
        predictions = [json.loads(line) for line in stream if line.strip()]
    if [p['image'] for p in predictions] != [s['image'] for s in selected]:
        raise ValueError('既有逐图预测不完整或与输入顺序不一致')
    return result


def evaluate(run, device, conf, continue_from=None, dry_run=False):
    runtime(run)
    integrity = verify(run)
    record = load(run/'run_record.json')
    if record['status'] != 'trained':
        raise ValueError('须先完成训练；不把初始化模型当作 E05 结果评估')
    best = run/'train/weights/best.pt'
    if sha(best) != record['training']['checkpoints']['best']['sha256']:
        raise ValueError('best.pt 已变化')
    prefix = 'val_' + str(conf).replace('.', 'p') + '_'
    if continue_from:
        output = Path(continue_from).expanduser().resolve()
        if output.parent != run.resolve() or not output.name.startswith(prefix) or not output.is_dir():
            raise ValueError('--continue-evaluation 须为此 run 下相同 conf 的既有 Val 目录')
    else:
        output = run/(prefix + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:6])
    if not dry_run:
        output.mkdir(exist_ok=bool(continue_from))
    results = {}
    for name, checkpoint in (('E01_s', BASELINE), ('E05_n', best)):
        directory = output/name
        if directory.exists():
            results[name] = completed_evaluation(directory, run, checkpoint, device, conf)
            print(f'[REUSE] {name}：完整结果及 hash 核验通过，不重复预测。', flush=True)
            continue
        print(f"[{'PLAN' if dry_run else 'RUN'}] {name} -> {directory}", flush=True)
        if dry_run:
            continue
        options = evaluation_options(run, checkpoint, device, conf)
        command = [sys.executable, str(ROOT/'script/model-evaluation/evaluate.py')]
        for key, value in options.items():
            command += ['--'+key.replace('_','-'), str(value)]
        subprocess.run(command + ['--output', str(directory)], check=True)
        results[name] = completed_evaluation(directory, run, checkpoint, device, conf)
    if dry_run:
        print('预检查通过；未启动预测或改写已有结果。', flush=True)
        return
    verify(run)
    a, b = results['E01_s'], results['E05_n']
    dump(output/'comparison.json', dict(conf=conf, E01_s=a, E05_n=b, deployment_benchmark='not_run',
         orchestration_sha256=sha(__file__), input_integrity=integrity,
         metrics_sha256={n:sha(output/n/'metrics.json') for n in results}))
    keys = ('mAP50', 'mAP50_95', 'precision', 'recall', 'no_ball_false_positive_rate')
    lines = ['# E05 同口径 Val 对照', '', f'工作阈值 conf={conf}，NMS IoU=0.7；同一完整 Val 1223 张；Test 未访问。', '',
             '| 指标 | E01 s | E05 n |', '|---|---:|---:|']
    lines += [f"| {k} | {a['metrics'][k]} | {b['metrics'][k]} |" for k in keys]
    lines += ['', '初始化经历不同：E01 使用已训练足球的 s，E05 使用官方通用预训练 n。',
              '此处不报告机器人速度；需独立构建 TensorRT 并进行同条件系统 A/B。']
    (output/'COMPARISON.md').write_text('\n'.join(lines)+'\n')
    print(output/'COMPARISON.md')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=('prepare', 'verify', 'train', 'evaluate', 'status'))
    p.add_argument('--run')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--continue-evaluation', metavar='VAL_DIR', help='evaluate：核验并复用已完成模型，只执行剩余模型')
    p.add_argument('--device', default='cpu', help='仅影响独立 Val；训练固定 E01 的 device=0')
    p.add_argument('--conf', type=float, choices=(.25,.45), default=.45)
    a = p.parse_args()
    if a.stage == 'prepare':
        prepare()
        return
    run = run_path(a.run)
    if a.stage == 'train':
        train(run, a.resume, a.dry_run)
    elif a.stage == 'verify':
        print(json.dumps(verify(run), ensure_ascii=False, indent=2))
    elif a.stage == 'evaluate':
        evaluate(run, a.device, a.conf, a.continue_evaluation, a.dry_run)
    else:
        print(f'运行目录：{run}')
        print(json.dumps(load(run/'run_record.json'), ensure_ascii=False, indent=2))
        if (run/'progress.json').exists():
            print(json.dumps(load(run/'progress.json'), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
