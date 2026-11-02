"""Audits for paired continuation experiments; uses the shared dataset/Trainer APIs."""
from contextlib import contextmanager
import csv
from functools import wraps
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

PATH_KEYS = {'model', 'data', 'project', 'save_dir'}


def config_diff(reference, candidate, ignore=PATH_KEYS):
    return {k: {'reference': reference.get(k), 'candidate': candidate.get(k)}
            for k in sorted(reference.keys() | candidate.keys())
            if k not in ignore and reference.get(k) != candidate.get(k)}


def assert_no_kd(config):
    # dis=0 alone still constructs a teacher in the pinned Trainer.
    if config.get('distill_model') is not None or config.get('resume'):
        raise ValueError('control requires distill_model=null and a new optimizer (no resume)')


def assert_pair(reference, candidate):
    assert_no_kd(candidate)
    if not reference.get('distill_model') or reference.get('dis') != 6.0:
        raise ValueError('reference is not the frozen E07 KD recipe')
    diff = config_diff(reference, candidate)
    if set(diff) != {'distill_model'}:
        raise ValueError(f'additional configuration differences: {diff}')
    return diff


def canonical_hash(files, root):
    content = {str(Path(p).relative_to(root)): digest for p, digest in files.items()}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def frozen_dataset(base, run, reference, data_root):
    """Relocate only the frozen Train/Val paths, never open a Test payload."""
    import yaml
    data_root = data_root.resolve()
    old = base.load(reference/'train_val_expected_hashes.json')
    expected = {}
    for name, digest in old.items():
        path = Path(name)
        tail = path.parts[-3:]
        if len(tail) != 3 or tail[0] not in ('images', 'labels') or tail[1] not in ('train', 'val'):
            raise ValueError(f'non Train/Val path in reference: {name}')
        target = data_root.joinpath(*tail)
        if target.resolve() != target:  # a symlink must not redirect into Test
            raise ValueError(f'symlink in source dataset: {target}')
        if str(target) in expected:
            raise ValueError('duplicate relocated input')
        expected[str(target)] = digest
    anchors = base.load(reference/'protected_inputs.json')
    for relative in ('manifest.csv', 'metadata.csv', 'lists/train.txt', 'lists/val.txt'):
        matches = [v for k, v in anchors.items() if k.endswith('/datasets/v1/'+relative)]
        if len(matches) != 1 or base.sha(data_root/relative) != matches[0]:
            raise ValueError(f'frozen dataset index differs: {relative}')
    config = dict(path=str(data_root), train='images/train', val='images/val',
                  nc=1, names={0: 'football'}, channels=3)
    (run/'dataset.val-evaluation.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
    io = base.module('control_dataset_io', base.ROOT/'script/model-evaluation/dataset_io.py')
    observed, counts = {}, {}
    for split, count in base.COUNTS.items():
        for kind in ('images', 'labels'):
            directory = data_root/kind/split
            if directory.resolve() != directory:
                raise ValueError('source split must not be a symlink')
            actual = {str(p) for p in directory.iterdir()}
            frozen = {p for p in expected if Path(p).parent == directory}
            if actual != frozen:
                raise ValueError(f'{kind}/{split} membership differs from E07')
        selection = io.select(run/'dataset.val-evaluation.yaml', split, data_root/'metadata.csv')
        if selection.skipped or len(selection.samples) != count:
            raise ValueError(f'incomplete frozen {split}')
        for sample in selection.samples:
            if sample.image.suffix.lower() in ('.jpg', '.jpeg'):
                with sample.image.open('rb') as stream:
                    stream.seek(-2, 2)
                    if stream.read() != b'\xff\xd9':
                        raise ValueError('JPEG could be repaired in place by Trainer')
            for kind, path, key in [('images', sample.image, 'image_sha256'),
                                    ('labels', sample.label, 'label_sha256')]:
                observed[str(path)] = sample.hashes[key]
                if expected.get(str(path)) != sample.hashes[key]:
                    raise ValueError(f'E07 content differs: {path}')
                dest = run/'runtime/dataset'/kind/split/path.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.symlink_to(path)
        counts[split] = dict(images=len(selection.samples), boxes=sum(len(s.gt) for s in selection.samples))
    if observed != expected:
        raise ValueError('Train/Val fingerprint inventory mismatch')
    config['path'] = str(run/'runtime/dataset')
    (run/'dataset.train-val.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
    base.dump(run/'train_val_expected_hashes.json', expected)
    return dict(counts=counts, content_sha256=canonical_hash(expected, data_root))


@contextmanager
def no_teacher_load(allowed, output):
    """Trap native KD construction and every Ultralytics checkpoint load."""
    from ultralytics.nn import tasks
    from ultralytics.nn.distill_model import DistillationModel
    permitted = {Path(p).resolve() for p in allowed}
    evidence = dict(teacher_loads=0, teacher_construction_attempts=0, checkpoint_loads=[])
    original = tasks.torch_safe_load

    def load(weight, *args, **kwargs):
        path = Path(weight).resolve()
        if path not in permitted and output.resolve() not in path.parents:
            raise ValueError(f'undeclared checkpoint load (teacher forbidden): {path}')
        evidence['checkpoint_loads'].append(str(path))
        return original(weight, *args, **kwargs)

    def forbidden(*args, **kwargs):
        evidence['teacher_construction_attempts'] += 1
        raise ValueError('DistillationModel construction is forbidden in the control')

    with patch.object(tasks, 'torch_safe_load', load), patch.object(DistillationModel, '__init__', forbidden):
        yield evidence


def audit_student(base, trainer, initial, counts):
    import torch
    from ultralytics import YOLO
    assert_no_kd(vars(trainer.args))
    model = trainer.model
    base.check_nano(model, 1)
    if (any(hasattr(model, name) for name in ('teacher_model', 'student_model', 'projector'))
            or any('teacher' in k or 'projector' in k for k in model.state_dict())
            or model.names != {0: 'football'} or not trainer.args.nms):
        raise ValueError('control is not an ordinary single-class dual-head nano')
    if (len(trainer.train_loader.dataset) != counts['train']
            or len(trainer.test_loader.dataset) != counts['val'] or trainer.data.get('test')):
        raise ValueError('unexpected Train/Val or Test configured')
    expected = YOLO(str(initial)).model.float().state_dict()
    actual = model.state_dict()
    if expected.keys() != actual.keys() or any(not torch.equal(v, actual[k].cpu()) for k, v in expected.items()):
        raise ValueError('initialization is not tensor-identical before the first update')
    return dict(initialization_tensors_exact=True, tensor_count=len(expected), teacher_loaded=False,
                projector_parameters=0, parameters=sum(p.numel() for p in model.parameters()))


def count_updates(trainer):
    counters = dict(optimizer_step_attempts=0, optimizer_updates=0, batches=0)
    def applied(*args):
        counters['optimizer_updates'] += 1
    trainer.optimizer.register_step_post_hook(applied)
    original = trainer.optimizer_step
    @wraps(original)
    def step():
        counters['optimizer_step_attempts'] += 1
        return original()
    trainer.optimizer_step = step
    return counters


def csv_budget(run, record, maximum=100, patience=30):
    """CSV counts exclude the final-validation callback; absent evidence stays not_run."""
    path = run/'train/results.csv'
    if record.get('status') != 'trained' or not path.is_file():
        return dict(status='not_run', reason='completed training and results.csv required',
                    max_epochs=maximum, patience=patience)
    with path.open() as stream:
        rows = [{k.strip(): v.strip() for k, v in r.items()} for r in csv.DictReader(stream)]
    if not rows or [int(r['epoch']) for r in rows] != list(range(1, len(rows)+1)):
        raise ValueError('training CSV has missing, repeated or unordered epochs')
    best = max(rows, key=lambda r: (float(r['metrics/mAP50-95(B)']), int(r['epoch'])))
    epochs, best_epoch = len(rows), int(best['epoch'])
    elapsed = record.get('training', {}).get('elapsed_seconds', 'not_run')
    if record.get('training', {}).get('resume_events'):
        elapsed = 'not_run'  # legacy elapsed is last invocation, not a sum of resumes
    return dict(status='complete', epochs_completed=epochs, best_csv_map_epoch=best_epoch,
                max_epochs=maximum, patience=patience, unused_epoch_allowance=maximum-epochs,
                stop_reason='early_stopping' if epochs < maximum and epochs-best_epoch >= patience
                else ('max_epochs' if epochs == maximum else 'unknown'),
                elapsed_seconds=elapsed,
                stop_reason_evidence='inferred_from_csv; rounded metrics may hide ties',
                optimizer_updates='not_run', optimizer_step_attempts='not_run',
                results_csv=str(path))
