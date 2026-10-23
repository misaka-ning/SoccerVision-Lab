#!/usr/bin/env python3
"""Prepare E02 safely; training only runs under the explicit train command."""
from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from uuid import uuid4

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / 'baseline/E1_baseline.pt'
SOURCE_SHA = '285c198aff043fe7e7486515dbdc1a2cc02db5daf9a0f55f8ce3c6cabf2743ac'
PARENT = ROOT / 'experiments/E01_baseline/runs/20261019T092432Z_s42_853c4a'
DATA = ROOT / 'datasets/v1'


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def environment(run):
    os.environ.update(YOLO_OFFLINE='true', YOLO_AUTOINSTALL='false', PYTHONDONTWRITEBYTECODE='1',
                      YOLO_CONFIG_DIR=str(run/'runtime/yolo'), MPLCONFIGDIR=str(run/'runtime/matplotlib'),
                      OMP_NUM_THREADS='4', MKL_NUM_THREADS='4', OPENBLAS_NUM_THREADS='4',
                      CUBLAS_WORKSPACE_CONFIG=':4096:8')


def shared_train():
    spec = importlib.util.spec_from_file_location('e02_shared_train', ROOT/'script/model-training/train.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dataset_view(run):
    """Use formal manifest membership, not historical absolute paths in lists."""
    import yaml
    manifest = list(csv.DictReader((DATA/'manifest.csv').open(encoding='utf-8-sig', newline='')))
    metadata = {row['图片']: row for row in csv.DictReader((DATA/'metadata.csv').open(encoding='utf-8-sig', newline=''))}
    view = run/'runtime/dataset'
    fingerprints, counts = {}, {}
    for split, expected in [('train', 4346), ('val', 1223)]:
        selected = [r for r in manifest if r['usage'] == split]
        names = [r['filename'] for r in selected]
        frozen_names = [Path(x.strip()).name for x in (DATA/'lists'/f'{split}.txt').read_text(encoding='utf-8-sig').splitlines() if x.strip()]
        actual = {p.name for p in (DATA/'images'/split).iterdir() if p.is_file()}
        if len(selected) != expected or len(set(names)) != expected or set(names) != set(frozen_names) or len(frozen_names) != expected or actual != set(names):
            raise ValueError(f'Frozen {split} membership/count mismatch')
        for kind in ['images', 'labels']:
            (view/kind/split).mkdir(parents=True)
        boxes = 0
        for row in selected:
            image = DATA/'images'/split/row['filename'];label = DATA/'labels'/split/(image.stem+'.txt')
            if not image.is_file() or not label.is_file():
                raise FileNotFoundError(str(image))
            review = metadata[image.name]
            if review['split'] != split or review['label_review_required'] != '0' or review['scene_review_required'] != '0' or review['annotation_status'] == 'reviewed_excluded':
                raise ValueError(f'Unreviewed/excluded source: {image.name}')
            if sha(label) != row['label_sha256']:
                raise ValueError(f'Label hash changed: {label}')
            for line in label.read_text().splitlines():
                if line.strip():
                    values = line.split()
                    if len(values) != 5 or values[0] != '0':raise ValueError(f'Not single-class detection: {label}')
                    boxes += 1
            for kind, source, expected_hash in [('images', image, row['image_sha256']), ('labels', label, row['label_sha256'])]:
                (view/kind/split/source.name).symlink_to(source)
                fingerprints[str(source)] = expected_hash
        counts[split] = dict(images=len(selected), boxes=boxes)
    data = dict(path=str(view), train='images/train', val='images/val', nc=1, names={0:'football'}, channels=3)
    (run/'dataset.train-val.yaml').write_text(yaml.safe_dump(data, sort_keys=False))
    (run/'dataset.val-evaluation.yaml').write_text(yaml.safe_dump(dict(path=str(DATA), train='images/train', val='images/val', nc=1, names={0:'football'}), sort_keys=False))
    dump(run/'train_val_expected_hashes.json', fingerprints)
    return counts


def prepare(args):
    import yaml
    if sha(SOURCE) != SOURCE_SHA:
        raise ValueError('E1 source checkpoint changed; audit it before creating E02')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + f'_s42_{uuid4().hex[:6]}_{args.variant}'
    run = HERE/'runs'/run_id
    run.mkdir(parents=True, exist_ok=False)
    environment(run)
    dump(run/'run_record.json', dict(status='preparing', created_utc=now(), training_started=False))
    try:
        import torch
        import ultralytics
        from ultralytics import YOLO
        from ultralytics.nn.tasks import DetectionModel
        from migrate import transfer_model
        if ultralytics.__version__ != '8.4.173':
            raise ValueError('Use the E1-compatible Ultralytics 8.4.173 runtime')
        torch.set_num_threads(4);torch.manual_seed(42)
        original = YOLO(str(SOURCE), task='detect')
        source = original.model.float().cpu().eval()
        before = deepcopy(source.yaml);before.pop('yaml_file', None)
        after = yaml.safe_load((HERE/'architecture.yaml').read_text())
        expected = deepcopy(before)
        if expected['head'][8] != [-1, 2, 'C3k2', [512, True]]:
            raise ValueError('Source layer19 does not match the audited E1 architecture')
        expected['head'][8][3].append(0.4375)
        if after != expected or len(before['backbone']) != 11 or source.names != {0:'football'}:
            raise ValueError('Only the exact layer19 expansion change is allowed')
        chosen = before if args.variant == 'control' else after
        (run/'architecture.yaml').write_text(yaml.safe_dump(chosen, sort_keys=False))
        target = DetectionModel(deepcopy(chosen), ch=3, nc=1, verbose=False).float().eval()
        target.names = {0:'football'}
        transfer = transfer_model(source, target)
        if (source.model[19].c, target.model[19].c) != (128, 128 if args.variant == 'control' else 112):
            raise ValueError('Unexpected actual hidden width')
        # A bounded synthetic forward is a shape check, never a training step.
        captures = {}
        def capture(label):
            def hook(module, inputs, output):captures[label] = output.detach().clone()
            return hook
        h1=source.model[16].register_forward_hook(capture('source_p3'));h2=target.model[16].register_forward_hook(capture('target_p3'))
        hooks=[];shapes={}
        for index in [19,22]:
            def shape_hook(module, inputs, output, index=index):shapes[str(index)] = list(output.shape)
            hooks.append(target.model[index].register_forward_hook(shape_hook))
        training_head = target.end2end
        target.end2end=False
        with torch.inference_mode():
            x=torch.rand(1,3,640,640);source(x);output=target(x)
        h1.remove();h2.remove()
        for hook in hooks:hook.remove()
        raw=output[0] if isinstance(output,tuple) else output
        assert list(raw.shape)==[1,5,8400] and torch.isfinite(raw).all(), f'Invalid raw output {raw.shape}'
        assert torch.equal(captures['source_p3'],captures['target_p3']), f'P3 changed before training; max abs={(captures["source_p3"]-captures["target_p3"]).abs().max().item()}'
        target.end2end=training_head
        # In this runtime, end2end selects inference only; dual training is
        # selected by the presence of one2one_cv2 (init_criterion -> E2ELoss).
        assert chosen['end2end'] is True and getattr(target.model[-1], 'one2one_cv2', None) is not None, 'Dual training head missing'
        original.model=target
        original.ckpt=dict(epoch=-1, optimizer=None, train_args={'task':'detect','model':str(run/'architecture.yaml')})
        original.save(run/'init.pt')
        loaded=YOLO(str(run/'init.pt'), task='detect').model.float()
        for key,value in target.state_dict().items():
            assert torch.equal(value,loaded.state_dict()[key]),key
        # Official future Trainer.get_model uses DetectionModel.load. Ensure
        # every initialized tensor survives this rebuild, before any training.
        rebuilt=DetectionModel(deepcopy(chosen), ch=3, nc=1, verbose=False).float()
        rebuilt.names={0:'football'};rebuilt.load(loaded,verbose=False)
        assert all(torch.equal(v,rebuilt.state_dict()[k])for k,v in loaded.state_dict().items()), 'Official reload discarded initialized values'
        dump(run/'transfer.json',transfer)
        counts=dataset_view(run)
        config=yaml.safe_load((HERE/'train.template.yaml').read_text())
        config.update(model=str(run/'init.pt'), data=str(run/'dataset.train-val.yaml'), project=str(run), name='train',exist_ok=False)
        (run/'train.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        shared=shared_train();shared.build_plan(shared.parse_args(['--config',str(run/'train.yaml')]))
        version_probe=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,memory.free,driver_version','--format=csv,noheader'],capture_output=True,text=True)
        env=dict(python=sys.version,executable=sys.executable,platform=platform.platform(),torch=torch.__version__,ultralytics=ultralytics.__version__,cuda=torch.version.cuda,cuda_available=torch.cuda.is_available(),gpu_probe=dict(returncode=version_probe.returncode,stdout=version_probe.stdout,stderr=version_probe.stderr),packages={d.metadata['Name']:d.version for d in importlib.metadata.distributions()})
        dump(run/'environment.json',env)
        protected=[SOURCE,Path(__file__),HERE/'migrate.py',ROOT/'script/model-training/train.py',HERE/'architecture.yaml',HERE/'train.template.yaml',DATA/'manifest.csv',DATA/'metadata.csv',DATA/'manifest.json',DATA/'dataset.yaml',DATA/'lists/train.txt',DATA/'lists/val.txt',run/'init.pt',run/'architecture.yaml',run/'train.yaml',run/'dataset.train-val.yaml',run/'train_val_expected_hashes.json']
        dump(run/'protected_inputs.json',{str(p):sha(p)for p in protected})
        check=dict(status='passed',training_started=False,optimizer_steps=0,synthetic_forward='CPU FP32, 1x3x640x640; one-to-many inference only',source_hidden=128,target_hidden=target.model[19].c,layer19_input_channels=target.model[19].cv1.conv.in_channels,layer19_output_channels=target.model[19].cv2.conv.out_channels,p3_identical_before_training=True,p3_shape=list(captures['target_p3'].shape),output_shapes=shapes,raw_shape=list(raw.shape),source_parameters=sum(p.numel()for p in source.parameters()),candidate_parameters=sum(p.numel()for p in target.parameters()),checkpoint_roundtrip_exact=True,official_reload_exact=True,data=counts,train_val_image_hashes_checked=False,test_pixels_or_labels_opened=False,checkpoint_inference_end2end_before=source.end2end,prepared_inference_end2end=target.end2end,dual_training_branches_present=True)
        dump(run/'precheck.json',check)
        record=json.loads((ROOT/'experiments/_template/run_record.json').read_text())
        record.update(template_only=False,experiment_id=HERE.name,run_id=run_id,status='prepared',created_utc=now(),parent_run_id=PARENT.name,purpose='E1 continued-training control'if args.variant=='control'else'Layer19 e=0.4375 recovery pilot',variant=args.variant,training_started=False)
        files=[HERE/'e02.py',HERE/'migrate.py',HERE/'architecture.yaml',HERE/'train.template.yaml',ROOT/'script/model-training/train.py',ROOT/'script/common/dataset_config.py']
        record['source'].update(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),dirty=True,script_hashes={str(p.relative_to(ROOT)):sha(p)for p in files})
        snapshot=run/'source';snapshot.mkdir()
        for p in files:
            dest=snapshot/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes())
        (snapshot/'git_status.txt').write_text(subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True))
        record['initialization'].update(mode=transfer['strategy'],path=str(SOURCE),sha256=SOURCE_SHA,source_run_id=PARENT.name,total_tensor_count=transfer['total_tensors'],newly_initialized_modules=[],exposure=dict(evidence_ref=str(PARENT/'run_record.json'),current_test_seen=False,some_training_images_seen=True,unknown_details=[]))
        record['architecture'].update(file='architecture.yaml',sha256=sha(run/'architecture.yaml'),variant='E1 control'if args.variant=='control'else'YOLO26s L19 e=0.4375',class_count=1,output_strides=[8,16,32],parameter_count=check['candidate_parameters'])
        record['data'].update(version='v1',frozen_manifest_sha256=sha(DATA/'manifest.csv'),metadata_sha256=sha(DATA/'metadata.csv'),counts={k:v['images']for k,v in counts.items()},relation='Frozen Train/Val only; Test not accessed')
        record['training'].update(enabled=False,config_ref='train.yaml',config_sha256=sha(run/'train.yaml'),seed=42,deterministic=True,device=config['device'],actual_output_ref=str(run/'train'),best_selection_rule='Official Val fitness, same E1 recipe; not yet trained')
        record['environment'].update(python=sys.version,pytorch=torch.__version__,ultralytics=ultralytics.__version__,cuda=torch.version.cuda,dependencies_ref='environment.json')
        record['baseline_reference'].update(path=str(SOURCE),sha256=SOURCE_SHA)
        dump(run/'run_record.json',record)
        pointer=HERE/'LOCAL_READY.json';ready=json.loads(pointer.read_text())if pointer.exists()else{}
        ready[args.variant]=str(run);dump(pointer,ready)
        print(json.dumps(dict(run=str(run),**check),ensure_ascii=False,indent=2))
        return 0
    except BaseException as exc:
        import traceback
        (run/'prepare_error.log').write_text(traceback.format_exc())
        dump(run/'run_record.json',dict(status='prepare_failed',failure=str(exc),training_started=False,created_utc=now()))
        raise


def train(args):
    run=Path(args.run).expanduser().resolve()if args.run else Path(json.loads((HERE/'LOCAL_READY.json').read_text())[args.variant])
    if not run.is_relative_to((HERE/'runs').resolve()):raise ValueError('Run must be inside this experiment')
    record=json.loads((run/'run_record.json').read_text())
    if record['status']!='prepared':raise ValueError('Not a fresh prepared run; prepare a new run or explicitly resume the training checkpoint')
    environment(run)
    shared=shared_train();plan=shared.parse_args(['--config',str(run/'train.yaml')]);shared.build_plan(plan)
    for path,expected in json.loads((run/'protected_inputs.json').read_text()).items():
        if sha(path)!=expected:raise ValueError(f'Protected input changed: {path}; prepare a new run')
    if args.dry_run:
        print(f'Prepared run: {run}\nConfig check passed; training not started. Image hashes are checked only when training starts.')
        return 0
    if (run/'train').exists():raise FileExistsError('Refusing to overwrite an existing train directory')
    lock=run/'.train.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    try:
        # Full Train/Val content checks are deferred to the user's launch.
        for path,expected in json.loads((run/'train_val_expected_hashes.json').read_text()).items():
            if sha(path)!=expected:raise ValueError(f'Frozen Train/Val content changed: {path}')
            if Path(path).suffix.lower()in{'.jpg','.jpeg'}:
                with open(path,'rb')as f:f.seek(-2,2);tail=f.read()
                if tail!=b'\xff\xd9':raise ValueError(f'JPEG repair would modify a frozen image: {path}')
        record.update(status='training',training_started=True,training_started_utc=now());record['training']['enabled']=True;dump(run/'run_record.json',record)
        command=[sys.executable,'-B',str(ROOT/'script/model-training/train.py'),'--config',str(run/'train.yaml')]
        with (run/'training.log').open('x')as log:
            proc=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            try:
                for line in proc.stdout:print(line,end='',flush=True);log.write(line);log.flush()
                code=proc.wait()
            except BaseException:
                proc.terminate();proc.wait();raise
        record.update(status='trained_pending_evaluation'if code==0 else'training_failed',completed_utc=now(),training_returncode=code)
        for name in ['best','last']:
            checkpoint=run/'train/weights'/f'{name}.pt'
            if checkpoint.is_file():record['training'][f'{name}_checkpoint_ref']=str(checkpoint);record['training']['checkpoint_sha256'][name]=sha(checkpoint)
        dump(run/'run_record.json',record);return code
    except BaseException as exc:
        record.update(status='failed_or_interrupted',failure=str(exc),completed_utc=now());dump(run/'run_record.json',record);raise


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare',help='Create a new init/check/config run; never train');prep.add_argument('--variant',choices=['candidate','control'],default='candidate')
    launch=sub.add_parser('train',help='Explicit user-invoked training through shared train.py');launch.add_argument('--run');launch.add_argument('--variant',choices=['candidate','control'],default='candidate');launch.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    try:return prepare(args)if args.command=='prepare'else train(args)
    except (ValueError,OSError,AssertionError,KeyError)as exc:print(f'E02 error: {exc}',file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
