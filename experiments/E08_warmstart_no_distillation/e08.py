#!/usr/bin/env python3
"""E08: E05 best.pt continuation, paired with E07, distill_model=null."""
from contextlib import contextmanager
from datetime import datetime, timezone
import difflib
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import uuid4

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT/'script/experiment-tools'))
import warm_control as control

spec = importlib.util.spec_from_file_location('e08_e07', ROOT/'experiments/E07_warmstart_distillation/e07.py')
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)
base = reference.base
sha, dump, load, now = base.sha, base.dump, base.load, base.now
E07_RUN = ROOT/'experiments/E07_warmstart_distillation/runs/20261023T035555Z_s42_WarmKD_93e0cf'
STUDENT_SHA = reference.STUDENT_BEST_SHA


def config_for(run, kd=False):
    import yaml
    config = yaml.safe_load((reference.E05/'train.template.yaml').read_text())
    config.update(model=str(run/'init.pt'), data=str(run/'dataset.train-val.yaml'), project=str(run),
                  distill_model=str(reference.TEACHER) if kd else None, dis=6.0)
    return config


def run_path(value):
    run = Path(value).resolve() if value else Path(load(HERE/'LOCAL_READY.json')['run']).resolve()
    if run.parent != (HERE/'runs').resolve() or load(run/'run_record.json')['experiment_id'] != 'E08':
        raise ValueError('run must belong to E08/runs')
    return run


@contextmanager
def gpu_lock():
    with (reference.E05/'.training.lock').open('a') as shared, (HERE/'.training.lock').open('a') as own:
        try:
            for stream in (shared, own):
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('E05/E06/E07/E08 GPU task already running') from None
        yield


def verify(run):
    record = load(run/'run_record.json')
    root = Path(record['data_root'])
    count = 0
    for filename in ('protected_inputs.json', 'train_val_expected_hashes.json'):
        for name, digest in load(run/filename).items():
            p = Path(name)
            # Reject forbidden split paths before opening any payload.
            if filename == 'train_val_expected_hashes.json':
                if (p.parts[-3] not in ('images', 'labels') or p.parts[-2] not in ('train', 'val')
                        or p != root.joinpath(*p.parts[-3:]) or p.resolve() != p):
                    raise ValueError('non Train/Val input')
            if sha(p) != digest:
                raise ValueError(f'frozen input changed: {p}; create a new run')
            count += 1
    expected = load(run/'train_val_expected_hashes.json')
    for split in ('train', 'val'):
        for kind in ('images', 'labels'):
            directory = run/'runtime/dataset'/kind/split
            if directory.resolve() != directory:
                raise ValueError('runtime split directory must not be redirected')
            members = {Path(p).name for p in expected if Path(p).parts[-3:-1] == (kind, split)}
            source = root/kind/split
            if source.resolve() != source or {p.name for p in source.iterdir()} != members:
                raise ValueError('source split membership differs; refuse recursive discovery')
            if {p.name for p in directory.iterdir()} != members:
                raise ValueError('runtime view membership differs')
            for name in members:
                link = directory/name
                if not link.is_symlink() or link.resolve() != root/kind/split/name:
                    raise ValueError('runtime view target differs; refuse before Trainer reads it')
    return dict(checked_files=count, unchanged=True, test_images_or_labels_opened=False)


def runtime(run):
    torch = base.runtime(run)
    if reference.libraries() != load(run/'library_contract.json'):
        raise ValueError('runtime differs from frozen E07 library contract')
    return torch


def effective_pair(run, effective):
    ref = load(run/'reference/train.effective.json')
    return control.assert_pair(ref, effective)


def evaluation_revision(run):
    """Archive shared evaluator; reproduce E07's documented zero-area admission repair."""
    destination = run/'evaluation_code'
    destination.mkdir()
    originals = {}
    for source in (ROOT/'script/model-evaluation').glob('*.py'):
        shutil.copy2(source, destination/source.name)
        originals[source.name] = sha(source)
    path = destination/'evaluate.py'
    original = path.read_text()
    before = 'np.any(xyxy[:,2:]<=xyxy[:,:2])'
    after = 'np.any(xyxy[:,2:]<xyxy[:,:2])'
    if original.count(before) != 1:
        raise ValueError('shared evaluator changed; review zero-area policy before preparing')
    revised = original.replace(before, after)
    path.write_text(revised)
    (destination/'source.diff').write_text(''.join(difflib.unified_diff(
        original.splitlines(True), revised.splitlines(True), fromfile='shared/evaluate.py', tofile='run/evaluate.py')))
    return dict(policy='finite non-reversed zero-area candidates retained as IoU=0; no filtering',
                original_sha256=originals, effective_sha256={p.name: sha(p) for p in destination.glob('*.py')})


def prepare(a):
    import yaml
    parent = Path(a.e07_run).resolve()
    e05 = Path(a.e05_run).resolve()
    initial = Path(a.init).resolve() if a.init else e05/'train/weights/best.pt'
    if initial.suffix != '.pt':
        raise ValueError('initialization must be a .pt checkpoint')
    # Missing history is not silently substituted by a template or a published metric.
    required = [parent/n for n in ('train.yaml', 'train.effective.json', 'library_contract.json',
                'protected_inputs.json', 'train_val_expected_hashes.json', 'run_record.json')]
    probe = reference.E05/'assets/yolo26n.pt'
    required += [initial, parent/'init.pt', e05/'run_record.json', probe]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise FileNotFoundError('required frozen sources missing: '+', '.join(missing))
    if sha(probe) != load(reference.E05/'PRETRAINED.json')['sha256']:
        raise ValueError('local AMP probe SHA differs from E05')
    if sha(initial) != STUDENT_SHA or sha(parent/'init.pt') != STUDENT_SHA:
        raise ValueError('E08 and E07 must use the exact E05 best.pt bytes')
    ref_record = load(parent/'run_record.json')
    if (ref_record.get('experiment_id') != 'E07' or ref_record.get('status') != 'trained'
            or ref_record['student_initialization']['sha256'] != STUDENT_SHA
            or ref_record['teacher']['sha256'] != reference.TEACHER_SHA):
        raise ValueError('expected completed E07 with the frozen student and teacher provenance')
    e05_record = load(e05/'run_record.json')
    if (e05_record.get('status') != 'trained'
            or e05_record['training']['checkpoints']['best']['sha256'] != STUDENT_SHA):
        raise ValueError('expected completed E05 best.pt provenance')
    ref_config = yaml.safe_load((parent/'train.yaml').read_text())
    run = HERE/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_s42_NoKD_'+uuid4().hex[:8])
    candidate = config_for(run)
    control.assert_pair(ref_config, candidate)
    # Validate reference metadata against its original protected manifest by path suffix.
    anchors = load(parent/'protected_inputs.json')
    for filename in ('train.yaml', 'init.pt', 'library_contract.json', 'train_val_expected_hashes.json'):
        expected = [digest for p, digest in anchors.items() if p.endswith('/'+parent.name+'/'+filename)]
        if len(expected) != 1 or sha(parent/filename) != expected[0]:
            raise ValueError(f'E07 frozen source changed: {filename}')
    run.mkdir(parents=True, exist_ok=False)
    record = dict(experiment_id='E08', variant='NoKD', status='preparing', created_utc=now(),
                  training_started=False, training={}, data_root=str(Path(a.data_root).resolve()),
                  e07_run=str(parent), e05_run=str(e05), test_images_or_labels_opened=False)
    dump(run/'run_record.json', record)
    try:
        (run/'reference').mkdir()
        for source in required:
            if source.parent == parent and source.suffix in ('.json', '.yaml'):
                shutil.copy2(source, run/'reference'/source.name)
        shutil.copy2(initial, run/'init.pt')
        shutil.copy2(parent/'library_contract.json', run/'library_contract.json')
        (run/'train.yaml').write_text(yaml.safe_dump(candidate, sort_keys=False))
        dataset = control.frozen_dataset(base, run, parent, Path(a.data_root))
        torch = runtime(run)
        from ultralytics.cfg import get_cfg
        effective = vars(get_cfg(overrides=candidate))
        diff = effective_pair(run, effective)
        dump(run/'train.effective.planned.json', effective)
        shared = base.module('e08_shared_train', ROOT/'script/model-training/train.py')
        shared.build_plan(shared.parse_args(['--config', str(run/'train.yaml')]))
        revision = evaluation_revision(run)
        dump(run/'evaluation_revision.json', revision)
        sources = [*HERE.glob('*.py'), *HERE.glob('*.sh'), *HERE.glob('*.json'),
                   * (ROOT/'script/experiment-tools').glob('*.py'),
                   reference.E05/'e05.py', reference.E05/'train.template.yaml', reference.E05/'PRETRAINED.json',
                   ROOT/'experiments/E07_warmstart_distillation/e07.py',
                   ROOT/'script/model-training/train.py', ROOT/'script/common/dataset_config.py',
                   * (ROOT/'script/model-evaluation').glob('*.py')]
        sources = [p for p in sources if p.name != 'LOCAL_READY.json']
        for path in sources:
            dest = run/'source'/path.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        (run/'source/git_status.txt').write_text(subprocess.check_output(['git', 'status', '--short'], cwd=ROOT, text=True))
        protected = [*sources, *required, * (run/'reference').glob('*'), * (run/'evaluation_code').glob('*'),
                     run/'init.pt', run/'train.yaml', run/'train.effective.planned.json', run/'library_contract.json',
                     run/'dataset.train-val.yaml', run/'dataset.val-evaluation.yaml', run/'train_val_expected_hashes.json',
                     run/'evaluation_revision.json']
        protected += [Path(a.data_root).resolve()/p for p in ('manifest.csv', 'metadata.csv', 'lists/train.txt', 'lists/val.txt')]
        dump(run/'protected_inputs.json', {str(p): sha(p) for p in protected})
        record.update(status='prepared', data=dataset, source_commit=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            student_initialization=dict(source=str(initial), sha256=STUDENT_SHA, same_as_E07=True,
                                        new_optimizer=True, source_best_epoch=43, source_run_epochs_completed=73),
            configuration_difference=diff, teacher_loaded=False, formal_metrics='not_run')
        dump(run/'run_record.json', record)
        dump(run/'input_integrity.prepared.json', verify(run))
        dump(HERE/'LOCAL_READY.json', dict(run=str(run), utc=now()))
        print(f'PREPARED {run}; smoke and formal training not_run')
    except BaseException as exc:
        record.update(status='prepare_failed', error=repr(exc))
        dump(run/'run_record.json', record)
        raise


def dry_run(run=None):
    config = config_for(run or Path('<E08-run>'))
    result = dict(stage='dry-run', training_started=False, teacher_loaded=False,
                  config=config, configuration_difference=control.assert_pair(config_for(run or Path('<E08-run>'), True), config))
    if run:
        verify(run)
        shared = base.module('e08_plan', ROOT/'script/model-training/train.py')
        model, args = shared.build_plan(shared.parse_args(['--config', str(run/'train.yaml')]))
        result.update(model=model, arguments=args, frozen_inputs='passed',
                      effective_difference=effective_pair(run, load(run/'train.effective.planned.json')))
    else:
        result['frozen_inputs'] = 'not_run: supply --run after prepare'
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def smoke(run):
    with gpu_lock():
        torch = runtime(run)
        verify(run)
        reference.gpu_ready(torch)
        if (run/'smoke').exists() or (run/'smoke_failed.json').exists():
            raise FileExistsError('smoke exists; preserve it and prepare a new run')
        from ultralytics.models.yolo.detect import DetectionTrainer
        import yaml
        config = yaml.safe_load((run/'train.yaml').read_text())
        config.update(project=str(run/'smoke'), plots=False, workers=0, save_period=-1)
        # Native AMP probe must already be local; never auto-download a checkpoint.
        probe = reference.E05/'assets/yolo26n.pt'
        if not probe.is_file():
            raise FileNotFoundError(f'local AMP probe required: {probe}')
        with control.no_teacher_load([run/'init.pt', probe], run/'smoke') as loads:
            started = time.perf_counter()
            try:
                result = one_step(run, config, base.COUNTS, DetectionTrainer, torch)
            except BaseException as exc:
                dump(run/'smoke_failed.json', dict(status='failed', error=repr(exc),
                    elapsed_seconds=time.perf_counter()-started, formal_training_started=False,
                    checkpoint_load_audit=loads))
                raise
            result['elapsed_seconds'] = time.perf_counter()-started
            result['checkpoint_load_audit'] = loads
        result.update(status='passed', train_yaml_sha256=sha(run/'train.yaml'), input_integrity=verify(run))
        dump(run/'preflight.json', result)
        print(json.dumps(result, indent=2))


def one_step(run, config, counts, trainer_class, torch):
    """Bounded smoke only: one real update, at most eight native AMP attempts."""
    from ultralytics.utils.torch_utils import autocast
    trainer = trainer_class(overrides=config)
    trainer._setup_train()
    if trainer.device.type == 'cuda' and (not trainer.amp or type(trainer.optimizer).__name__ != 'AdamW'):
        raise ValueError('smoke AMP/optimizer differs from E07')
    audit = control.audit_student(base, trainer, run/'init.pt', counts)
    counters = control.count_updates(trainer)
    initial = reference.state_hash(trainer.model)
    trainer._model_train()
    batch = trainer.preprocess_batch(next(iter(trainer.train_loader)))
    attempts = []
    for _ in range(8):
        trainer.optimizer.zero_grad(set_to_none=True)
        with autocast(trainer.amp):
            losses, items = trainer.model(batch)
            loss = losses.sum()
        if 'dis_loss' in items or not torch.isfinite(loss):
            raise ValueError('KD loss or nonfinite loss in control')
        trainer.scaler.scale(loss).backward()
        gradient = reference.gradient_stats(trainer.model, trainer.scaler.get_scale())
        before = counters['optimizer_updates']
        trainer.optimizer_step()
        attempts.append(dict(gradient=gradient, applied=counters['optimizer_updates'] > before))
        if counters['optimizer_updates']:
            if gradient['nonfinite_tensors'] or not gradient['unscaled_norm'] > 0:
                raise ValueError('invalid gradient in applied update')
            break
    else:
        raise ValueError('no applied optimizer update after 8 attempts')
    if reference.state_hash(trainer.model) == initial:
        raise ValueError('student did not update')
    if any(not torch.isfinite(p).all() for p in trainer.model.parameters()):
        raise ValueError('nonfinite student after update')
    trainer.epoch = 0
    trainer.fitness = trainer.best_fitness = 0.0
    trainer.save_model()
    saved = torch.load(trainer.last, map_location='cpu', weights_only=False)
    if saved['optimizer'] is None or any(hasattr(saved['ema'], k) for k in ('teacher_model', 'projector')):
        raise ValueError('smoke checkpoint is not an ordinary student with optimizer')
    return dict(formal_training_started=False, smoke_optimizer_updates=counters['optimizer_updates'],
                actual_batch=len(batch['img']), actual_imgsz=list(batch['img'].shape[2:]),
                loss_items={k: float(v) for k, v in items.items()}, attempts=attempts,
                initialization=audit, teacher_loaded=False, save_checkpoint='passed')


def train(run):
    with gpu_lock():
        torch = runtime(run)
        verify(run)
        record = load(run/'run_record.json')
        if record['status'] != 'prepared' or (run/'train').exists():
            raise ValueError('formal output exists or run not prepared; no overwrite/resume')
        preflight = load(run/'preflight.json')
        if (preflight['status'] != 'passed' or preflight['train_yaml_sha256'] != sha(run/'train.yaml')
                or preflight.get('actual_batch') != 8 or preflight.get('actual_imgsz') != [640, 640]
                or preflight.get('smoke_optimizer_updates') != 1
                or preflight.get('checkpoint_load_audit', {}).get('teacher_construction_attempts') != 0):
            raise ValueError('same-config real Train/Val smoke required')
        reference.gpu_ready(torch)
        from ultralytics import YOLO
        shared = base.module('e08_train', ROOT/'script/model-training/train.py')
        source, args = shared.build_plan(shared.parse_args(['--config', str(run/'train.yaml')]))
        control.assert_no_kd(args)
        counters = {}
        def ready(t):
            if t.save_dir.resolve() != (run/'train').resolve():
                raise ValueError('output directory drift')
            effective_pair(run, vars(t.args))
            setup = control.audit_student(base, t, run/'init.pt', base.COUNTS)
            if type(t.optimizer).__name__ != 'AdamW' or not t.amp:
                raise ValueError('effective optimizer or AMP differs from E07')
            dump(run/'formal_setup.json', setup)
            dump(run/'train.effective.json', vars(t.args))
            dump(run/'optimizer.effective.json', dict(name=type(t.optimizer).__name__, amp=bool(t.amp),
                accumulate=t.accumulate, groups=[{k: v for k, v in g.items() if k != 'params'} for g in t.optimizer.param_groups]))
            counters.update(actual=control.count_updates(t))
        def batch(t):
            counters['actual']['batches'] += 1
        def progress(t):
            dump(run/'budget.progress.json', counters['actual'])
        def saved(t):
            if t.last.exists():
                shutil.copy2(t.last, t.wdir/'resume-last.pt')
        record.update(status='training', training_started=True, pid=os.getpid())
        dump(run/'run_record.json', record)
        started = time.perf_counter()
        dump(run/'training_environment.json', dict(python=sys.version, executable=sys.executable,
            torch=torch.__version__, cuda=torch.version.cuda, gpu=torch.cuda.get_device_name(0),
            libraries=reference.libraries(),
            nvidia_smi=subprocess.check_output(['nvidia-smi'], text=True)))
        try:
            probe = reference.E05/'assets/yolo26n.pt'
            if not probe.is_file():
                raise FileNotFoundError('local AMP probe missing')
            with control.no_teacher_load([Path(source), probe], run/'train') as loads:
                model = YOLO(source, task='detect')
                for event, callback in [('on_pretrain_routine_end', ready), ('on_train_batch_end', batch),
                                         ('on_fit_epoch_end', progress), ('on_model_save', saved)]:
                    model.add_callback(event, callback)
                model.train(**args)
            verify(run)
            record.update(status='trained', completed_utc=now())
            record['training'].update(elapsed_seconds=time.perf_counter()-started,
                checkpoints={n: dict(path=str(run/f'train/weights/{n}.pt'), sha256=sha(run/f'train/weights/{n}.pt'))
                             for n in ('best', 'last')})
            budget = control.csv_budget(run, record)
            budget.update(counters['actual'], stop_reason_evidence='native stopper and completed CSV', best_fitness_epoch=int(model.trainer.stopper.best_epoch),
                          stop_reason='early_stopping' if model.trainer.stopper.possible_stop and budget['epochs_completed'] < 100 else budget['stop_reason'])
            dump(run/'training_budget.json', budget)
            dump(run/'no_teacher_load.json', loads)
        except BaseException as exc:
            record.update(status='training_failed', error=repr(exc))
            raise
        finally:
            dump(run/'run_record.json', record)


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=['prepare', 'dry-run', 'smoke', 'train', 'verify', 'compare', 'status'])
    p.add_argument('--run', help='explicit prepared E08 run; required for artifact operations')
    p.add_argument('--e07-run', default=str(E07_RUN))
    p.add_argument('--e05-run', default=str(reference.PARENT))
    p.add_argument('--init', help='optional relocated E05 best.pt; SHA must match E07')
    p.add_argument('--data-root', default=str(base.DATA))
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--evaluate', action='store_true', help='compare: explicitly run missing full Val evaluations')
    p.add_argument('--device', default='0')
    a = p.parse_args(argv)
    if a.dry_run and a.stage not in ('prepare', 'train', 'dry-run'):
        p.error('--dry-run is only valid for prepare/train/dry-run')
    if a.evaluate and a.stage != 'compare':
        p.error('--evaluate is only valid for compare')
    if a.stage == 'prepare':
        if a.dry_run:
            dry_run()
        else:
            prepare(a)
        return
    if a.stage == 'dry-run' or (a.stage == 'train' and a.dry_run):
        dry_run(run_path(a.run) if a.run else None)
        return
    if a.stage == 'compare':
        from compare import compare
        compare(sys.modules[__name__], run_path(a.run) if a.run else None, a.evaluate, a.device)
        return
    run = run_path(a.run)
    if a.stage == 'smoke':
        smoke(run)
    elif a.stage == 'train':
        train(run)
    elif a.stage == 'verify':
        print(json.dumps(verify(run)))
    else:
        print(json.dumps(load(run/'run_record.json'), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
