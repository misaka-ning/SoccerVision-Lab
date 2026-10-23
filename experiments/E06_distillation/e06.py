#!/usr/bin/env python3
"""E06/KD1: pinned native feature distillation, E01 teacher -> E05-initialized nano."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib
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
E05 = ROOT/'experiments/E05_yolo26n'
PARENT = E05/'runs/20261023T023231Z_s42_90bcea'
VAL = PARENT/'val_0p45_20261023T032229Z'
TEACHER = ROOT/'models_list/E01_baseline.pt'
TEACHER_SHA = '285c198aff043fe7e7486515dbdc1a2cc02db5daf9a0f55f8ce3c6cabf2743ac'
STUDENT_INIT = PARENT/'init.pt'
STUDENT_INIT_SHA = 'c3da7bd3f2ef6107640c36e8fb34dcef304b195f3115b958612cef711e062710'
STUDENT_BEST = PARENT/'train/weights/best.pt'
STUDENT_BEST_SHA = 'a51bf6f3ec855e7cb126d097fe30e213d0588d37a9f1d2d9546f090b168dfd13'
spec = importlib.util.spec_from_file_location('e06_e05_helpers', E05/'e05.py')
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)
sha, dump, load, now = base.sha, base.dump, base.load, base.now


def run_path(value=None):
    run = Path(value).expanduser().resolve() if value else Path(load(HERE/'LOCAL_READY.json')['run'])
    if run.parent != (HERE/'runs').resolve() or not (run/'run_record.json').is_file():
        raise ValueError('run 必须是 E06/runs 下的独立运行')
    return run


def libraries():
    names = ['ultralytics.nn.distill_model', 'ultralytics.nn.tasks', 'ultralytics.utils.loss',
             'ultralytics.utils.torch_utils', 'ultralytics.engine.trainer', 'ultralytics.engine.validator',
             'ultralytics.engine.model', 'ultralytics.models.yolo.detect.train']
    return {name:sha(importlib.import_module(name).__file__) for name in names}


def runtime(run):
    torch = base.runtime(run)
    if (run/'library_contract.json').exists() and libraries() != load(run/'library_contract.json'):
        raise ValueError('Ultralytics 蒸馏实现与准备时不同，禁止自动升级或绕过校验')
    return torch


def verify(run):
    count = 0
    for filename in ['protected_inputs.json', 'train_val_expected_hashes.json']:
        for path, expected in load(run/filename).items():
            if sha(path) != expected:
                raise ValueError(f'冻结输入变化：{path}；不重写原hash，请调查后新建run')
            count += 1
    return dict(utc=now(), checked_files=count, unchanged=True, test_images_or_labels_opened=False)


def training_config(run):
    config = base.recipe(run)
    config.update(distill_model=str(TEACHER), dis=6.0)
    return config


@contextmanager
def gpu_lock():
    # Coordinate with the existing E05 launcher too. These are local lockfiles only.
    with (E05/'.training.lock').open('a') as old, (HERE/'.training.lock').open('a') as current:
        try:
            fcntl.flock(old, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(current, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('E05/E06 已有训练或冒烟进程，请勿并发启动') from None
        yield


def gpu_ready(torch):
    # Check before creating a CUDA context; do not stop anybody else's process.
    probe = subprocess.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader,nounits'], text=True)
    others = [p.strip() for p in probe.splitlines() if p.strip().isdigit() and int(p.strip()) != os.getpid()]
    if others:
        raise ValueError(f'检测到其他 GPU 计算进程 {others}，本次未开始；请安排空闲窗口')
    if not torch.cuda.is_available():
        raise ValueError('CUDA不可用，不自动切CPU或修改batch')


def state_hash(model):
    h = hashlib.sha256()
    for key, value in sorted(model.state_dict().items()):
        array = value.detach().cpu().contiguous().numpy()
        h.update(key.encode()); h.update(str(array.dtype).encode()); h.update(str(array.shape).encode()); h.update(array.tobytes())
    return h.hexdigest()


def gradient_stats(model, scale):
    import torch
    gradients = [p.grad.detach() for p in model.parameters() if p.grad is not None]
    nonfinite = sum(not bool(torch.isfinite(g).all()) for g in gradients)
    norm = sum(float((g.float()/scale).norm()) for g in gradients) if nonfinite == 0 else None
    return dict(tensors=len(gradients),nonfinite_tensors=nonfinite,unscaled_norm=norm)


def audit_wrapper(trainer, initial=None):
    from ultralytics.nn.distill_model import DistillationModel
    import torch
    model = trainer.model
    if not isinstance(model, DistillationModel):
        raise ValueError('正式模型没有进入 DistillationModel，拒绝退化成普通训练')
    teacher, student = model.teacher_model, model.student_model
    base.check_nano(student, 1)
    if (teacher.yaml.get('scale') != 's' or teacher.names != {0:'football'} or teacher.training
            or any(p.requires_grad for p in teacher.parameters()) or student.names != {0:'football'}
            or model.feats_idx != [16,19,22,23] or model.teacher_feats_idx != [16,19,22,23]
            or model.dis != 6.0 or not trainer.args.nms or trainer.ema.ema.teacher_model is not None):
        raise ValueError('教师冻结、模型类别、蒸馏特征层或验证分支不符')
    if len(trainer.train_loader.dataset) != 4346 or len(trainer.test_loader.dataset) != 1223 or trainer.data.get('test'):
        raise ValueError('训练/验证集合不是原冻结 Train/Val')
    if initial is not None:
        from ultralytics import YOLO
        expected = YOLO(str(initial)).model.float().state_dict()
        if any(not torch.equal(value, student.state_dict()[key].cpu()) for key,value in expected.items()):
            raise ValueError('首次梯度更新前，学生与E05初始化不一致')
    return dict(teacher_state_sha256=state_hash(teacher), teacher_frozen=True, teacher_eval=True,
                student_parameters=sum(p.numel() for p in student.parameters()),
                projector_parameters=sum(p.numel() for p in model.projector.parameters()),
                student_features=model.feats_idx, teacher_features=model.teacher_feats_idx,
                dis=model.dis, dual_training_branches=True, validation_one_to_many=True)


def prepare():
    import yaml
    for path, expected in [(TEACHER,TEACHER_SHA),(STUDENT_INIT,STUDENT_INIT_SHA),(STUDENT_BEST,STUDENT_BEST_SHA)]:
        if sha(path) != expected:
            raise ValueError(f'固定教师/学生参考hash变化：{path}')
    base.verify(PARENT)
    for name, checkpoint in [('E01_s',TEACHER),('E05_n',STUDENT_BEST)]:
        base.completed_evaluation(VAL/name, PARENT, checkpoint, '0', .45)
    run = HERE/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_s42_KD1_'+uuid4().hex[:6])
    run.mkdir(parents=True, exist_ok=False)
    record = dict(experiment_id='E06',variant='KD1',run_id=run.name,status='preparing',created_utc=now(),
                  training_started=False,training={},test_images_or_labels_opened=False)
    dump(run/'run_record.json',record)
    try:
        torch = runtime(run)
        from ultralytics import YOLO
        shutil.copy2(STUDENT_INIT, run/'init.pt')
        student = YOLO(str(run/'init.pt')).model.cpu().float().eval()
        base.check_nano(student,1)
        student.end2end=False
        with torch.inference_mode(): output=student(torch.zeros(2,3,640,640))[0]
        if list(output.shape) != [2,5,8400] or not torch.isfinite(output).all():
            raise ValueError('学生输入输出契约失败')
        counts = base.dataset_view(run)
        config = training_config(run)
        (run/'train.yaml').write_text(yaml.safe_dump(config,sort_keys=False))
        shared = base.module('e06_shared_train',ROOT/'script/model-training/train.py')
        shared.build_plan(shared.parse_args(['--config',str(run/'train.yaml')]))
        dump(run/'library_contract.json',libraries())
        sources = sorted(HERE.glob('*.py')) + sorted(HERE.glob('*.sh'))
        sources += [E05/'e05.py', E05/'train.template.yaml', ROOT/'script/model-training/train.py', ROOT/'script/common/dataset_config.py']
        sources += sorted((ROOT/'script/model-evaluation').glob('*.py'))
        anchors = [TEACHER,STUDENT_INIT,STUDENT_BEST,run/'init.pt',run/'train.yaml',run/'dataset.train-val.yaml',
                   run/'dataset.val-evaluation.yaml',run/'train_val_expected_hashes.json',run/'library_contract.json',
                   base.DATA/'manifest.csv',base.DATA/'metadata.csv',base.DATA/'lists/train.txt',base.DATA/'lists/val.txt',
                   base.PARENT/'train.requested.yaml',base.PARENT/'input_fingerprints.json',VAL/'comparison.json']
        anchors += [VAL/n/f for n in ('E01_s','E05_n') for f in ('metrics.json','inputs_manifest.json','predictions.jsonl','status.json')]
        dump(run/'protected_inputs.json',{str(p):sha(p) for p in sources+anchors})
        for path in sources:
            target = run/'source'/path.relative_to(ROOT)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        (run/'source/git_status.txt').write_text(subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True))
        record.update(status='prepared',data=counts,teacher=dict(path=str(TEACHER),sha256=TEACHER_SHA),
             student_initialization=dict(path=str(STUDENT_INIT),sha256=STUDENT_INIT_SHA,same_as_E05=True),
             control=dict(run_id=PARENT.name,checkpoint_sha256=STUDENT_BEST_SHA,validation=str(VAL)),
             method='native score-weighted P3/P4/P5 feature L2, two-conv projectors, dis=6',
             source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
        dump(run/'run_record.json',record)
        dump(run/'input_integrity.prepared.json',verify(run))
        dump(HERE/'LOCAL_READY.json',dict(run=str(run),utc=now()))
        print(f'PREPARED: {run}\n正式训练之前须通过 smoke；尚未训练。',flush=True)
    except BaseException as exc:
        record.update(status='prepare_failed',error=repr(exc));dump(run/'run_record.json',record)
        raise


def smoke(run):
    """One real Train batch update plus save/resume/finalize checks; never a full run."""
    with gpu_lock():
        torch = runtime(run);verify(run);gpu_ready(torch)
        from ultralytics import YOLO
        from ultralytics.models.yolo.detect import DetectionTrainer
        from ultralytics.nn.distill_model import DistillationModel
        from ultralytics.utils.torch_utils import autocast, strip_optimizer
        import yaml
        config = yaml.safe_load((run/'train.yaml').read_text())
        config.update(project=str(run/'smoke'),name='train',plots=False,workers=0,save_period=-1)
        if (run/'smoke').exists():
            raise FileExistsError('smoke目录已存在，保留失败记录；不要覆盖后冒充首次检查')
        torch.cuda.reset_peak_memory_stats()
        trainer = DetectionTrainer(overrides=config)
        trainer._setup_train()
        before = audit_wrapper(trainer,run/'init.pt')
        trainer._model_train()
        batch = trainer.preprocess_batch(next(iter(trainer.train_loader)))
        kd = trainer.model
        attempts=[]
        # Native GradScaler can skip initial updates while calibrating its scale.
        # Do not mistake overflowing scaled gradients for a disconnected KD graph.
        for attempt in range(8):
            trainer.optimizer.zero_grad(set_to_none=True)
            with autocast(trainer.amp):
                losses,items=kd(batch)
                loss=losses.sum()
            if not torch.isfinite(loss) or 'dis_loss' not in items or not torch.isfinite(items['dis_loss']).all() or items['dis_loss'].sum()<=0:
                raise ValueError('KD损失缺失、非有限或没有实际贡献')
            trainer.scaler.scale(loss).backward()
            if any(p.grad is not None for p in kd.teacher_model.parameters()):raise ValueError('教师出现梯度')
            scale_before=trainer.scaler.get_scale()
            student_grad=gradient_stats(kd.student_model,scale_before)
            projector_grad=gradient_stats(kd.projector,scale_before)
            if student_grad['tensors']==0 or projector_grad['tensors']==0:raise ValueError('学生或投影层计算图未连接')
            trainer.optimizer_step()
            applied=trainer.scaler.get_scale()>=scale_before
            attempts.append(dict(attempt=attempt+1,scale_before=scale_before,scale_after=trainer.scaler.get_scale(),
                optimizer_update_applied=applied,student=student_grad,projector=projector_grad))
            if applied:
                if (student_grad['nonfinite_tensors'] or projector_grad['nonfinite_tensors']
                        or not student_grad['unscaled_norm']>0 or not projector_grad['unscaled_norm']>0):
                    raise ValueError('实际更新时学生或投影层梯度非法')
                break
        else:raise ValueError('8次原生AMP标定尝试后仍没有实际更新；不启动正式训练')
        if any(not torch.isfinite(p).all() for p in kd.student_model.parameters()) or any(not torch.isfinite(p).all() for p in kd.projector.parameters()):
            raise ValueError('实际更新后学生或投影层参数非有限')
        after = state_hash(kd.teacher_model)
        if after != before['teacher_state_sha256']:
            raise ValueError('教师参数或BN统计量发生变化')
        if any(p in trainer.optimizer.state for p in kd.teacher_model.parameters()):
            raise ValueError('教师被分配了优化器状态')
        trainer.epoch=0;trainer.fitness=0.0;trainer.best_fitness=0.0
        trainer.save_model()
        checkpoint = trainer.last
        result = dict(status='passed',utc=now(),formal_training_started=False,smoke_optimizer_steps=1,
            actual_train_batch=int(batch['img'].shape[0]),imgsz=list(batch['img'].shape[2:]),train_gt_boxes=len(batch['cls']),
            loss_items={k:float(v) for k,v in items.items()},teacher_unchanged=True,teacher_gradients_none=True,
            amp_scale_attempts=attempts,student_gradient_unscaled=student_grad,projector_gradient_unscaled=projector_grad,
            gpu_peak_allocated_bytes=torch.cuda.max_memory_allocated(),gpu_peak_reserved_bytes=torch.cuda.max_memory_reserved(),
            gpu_name=torch.cuda.get_device_name(0),torch=torch.__version__,cuda=torch.version.cuda,wrapper=before)
        del batch,loss,losses,items,kd,trainer
        import gc
        gc.collect();torch.cuda.empty_cache()
        # Exercise the actual native resume reconstruction and optimizer load.
        resumed = DetectionTrainer(overrides=dict(model=str(checkpoint),resume=str(checkpoint),device='0'))
        resumed._setup_train()
        audit_wrapper(resumed)
        saved = torch.load(checkpoint,map_location='cpu',weights_only=False)
        ema = saved['ema']
        if not isinstance(ema,DistillationModel) or ema.teacher_model is not None or not saved['optimizer']:
            raise ValueError('蒸馏恢复checkpoint结构错误')
        for key,value in ema.projector.float().state_dict().items():
            if not torch.equal(value,resumed.model.projector.state_dict()[key].cpu()):
                raise ValueError('恢复后投影层未精确载入')
        if resumed.start_epoch != 1 or not resumed.optimizer.state:
            raise ValueError('实际续训epoch/optimizer未恢复')
        result['native_resume'] = dict(passed=True,start_epoch_zero_based=1,projectors_exact=True,optimizer_loaded=True)
        del resumed
        gc.collect();torch.cuda.empty_cache()
        plain = run/'smoke/student_only.pt'
        strip_optimizer(checkpoint,s=str(plain))
        student = YOLO(str(plain)).model.cpu().float().eval()
        base.check_nano(student,1)
        if isinstance(student,DistillationModel) or any('projector' in k or 'teacher_model' in k for k in student.state_dict()):
            raise ValueError('部署学生仍携带蒸馏模块')
        for key,value in ema.student_model.float().state_dict().items():
            if not torch.equal(value,student.state_dict()[key]):
                raise ValueError('移除蒸馏包装时改变了学生权重')
        student.end2end=False
        with torch.inference_mode(): output=student(torch.rand(2,3,640,640))[0]
        if list(output.shape) != [2,5,8400] or not torch.isfinite(output).all():
            raise ValueError('学生独立推理失败')
        result['student_only_checkpoint'] = dict(passed=True,parameters=sum(p.numel() for p in student.parameters()),
              output_shape=list(output.shape),teacher_and_projectors_removed=True,state_values_exact=True)
        result['input_integrity']=verify(run)
        result['train_yaml_sha256']=sha(run/'train.yaml')
        dump(run/'preflight.json',result)
        print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)


def train(run, resume=False, dry_run=False):
    with gpu_lock():
        torch = runtime(run);verify(run)
        preflight = load(run/'preflight.json')
        if preflight['status'] != 'passed' or preflight['train_yaml_sha256'] != sha(run/'train.yaml'):
            raise ValueError('必须先通过同一配置的蒸馏冒烟检查')
        record=load(run/'run_record.json');out=run/'train'
        if record['status'] not in ('prepared','training','training_failed'):
            raise ValueError('此run已完成或不可训练')
        if not resume and out.exists():raise FileExistsError(out)
        shared=base.module('e06_shared_train',ROOT/'script/model-training/train.py')
        if resume:
            checkpoint=out/'weights/resume-last.pt'
            ckpt=torch.load(checkpoint,map_location='cpu',weights_only=False)
            from ultralytics.nn.distill_model import DistillationModel
            if ckpt.get('epoch',-1)<0 or not ckpt.get('optimizer') or not isinstance(ckpt.get('ema'),DistillationModel):
                raise ValueError('不是保留投影层与optimizer的蒸馏恢复checkpoint')
            source,args=shared.build_plan(shared.parse_args(['--resume',str(checkpoint),'--device','0']))
        else:
            source,args=shared.build_plan(shared.parse_args(['--config',str(run/'train.yaml')]))
        if dry_run:
            print(json.dumps(dict(model=source,args=args,smoke='passed',formal_training_started=False),ensure_ascii=False,indent=2));return
        gpu_ready(torch)
        from ultralytics import YOLO
        model=YOLO(str(source),task='detect')
        teacher_state={}
        def ready(t):
            if t.save_dir.resolve()!=out.resolve():raise ValueError('正式训练目录漂移')
            audit=audit_wrapper(t,None if resume else run/'init.pt')
            teacher_state.update(audit)
            dump(run/'formal_setup.json',audit)
            dump(run/'train.effective.json',vars(t.args))
            dump(run/'optimizer.effective.json',dict(name=type(t.optimizer).__name__,amp=bool(t.amp),accumulate=t.accumulate,
                groups=[{k:v for k,v in g.items() if k!='params'} for g in t.optimizer.param_groups]))
        def saved(t):
            if t.last.exists():
                temp=t.wdir/'resume-last.pt.tmp';shutil.copy2(t.last,temp);temp.replace(t.wdir/'resume-last.pt')
        def progress(t):
            rows=list(csv.DictReader(t.csv.open())) if t.csv.exists() else []
            dump(run/'progress.json',dict(utc=now(),epochs_completed=len(rows),requested_epochs=t.epochs,
                final_validation=t.epoch+1>len(rows),metrics=t.metrics,best_fitness=t.best_fitness))
        def ended(t):
            kd=t.model
            if state_hash(kd.teacher_model)!=teacher_state['teacher_state_sha256'] or any(p.grad is not None for p in kd.teacher_model.parameters()):
                raise ValueError('正式训练后教师发生变化')
            dump(run/'teacher_integrity.after_training.json',dict(unchanged=True,sha256=teacher_state['teacher_state_sha256']))
        for event,callback in [('on_pretrain_routine_end',ready),('on_model_save',saved),('on_fit_epoch_end',progress),('on_train_end',ended)]:
            model.add_callback(event,callback)
        if resume:record['training'].setdefault('resume_events',[]).append(dict(utc=now(),sha256=sha(source)))
        record.update(status='training',training_started=True,pid=os.getpid());dump(run/'run_record.json',record)
        dump(run/'training_environment.json',dict(python=sys.version,executable=sys.executable,torch=torch.__version__,cuda=torch.version.cuda,
             gpu=torch.cuda.get_device_name(0),nvidia_smi=subprocess.check_output(['nvidia-smi'],text=True),libraries=libraries()))
        started=time.perf_counter()
        try:
            model.train(**args)
            dump(run/'input_integrity.after_training.json',verify(run))
            for name in ('best','last'):
                saved_model=YOLO(str(out/f'weights/{name}.pt')).model
                base.check_nano(saved_model,1)
                if hasattr(saved_model,'teacher_model') or hasattr(saved_model,'projector'):raise ValueError('最终权重未去除教师/投影层')
            record.update(status='trained',completed_utc=now())
            record['training'].update(elapsed_seconds=time.perf_counter()-started,
                checkpoints={n:dict(path=str(out/f'weights/{n}.pt'),sha256=sha(out/f'weights/{n}.pt')) for n in ('best','last')})
        except BaseException as exc:
            record.update(status='training_failed',error=repr(exc));raise
        finally:dump(run/'run_record.json',record)
        print('E06/KD1 训练完成；请继续独立Val。TensorRT与机器人测试尚未执行。',flush=True)


def evaluate(run, device, conf):
    runtime(run);verify(run)
    record=load(run/'run_record.json')
    if record['status']!='trained':raise ValueError('先完成正式训练')
    best=run/'train/weights/best.pt'
    if sha(best)!=record['training']['checkpoints']['best']['sha256']:raise ValueError('best.pt hash变化')
    output=run/('val_'+str(conf).replace('.','p')+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:6])
    output.mkdir()
    results={}
    for name,checkpoint in [('E01_s',TEACHER),('E05_n',STUDENT_BEST),('E06_KD1',best)]:
        directory=(VAL/name) if conf==.45 and device=='0' and name!='E06_KD1' else output/name
        if directory.exists():
            results[name]=base.completed_evaluation(directory,PARENT,checkpoint,device,conf)
            print(f'[REUSE] {name}',flush=True)
        else:
            command=[sys.executable,str(ROOT/'script/model-evaluation/evaluate.py')]
            for k,v in base.evaluation_options(run,checkpoint,device,conf).items():command+=['--'+k.replace('_','-'),str(v)]
            subprocess.run(command+['--output',str(directory)],check=True)
            results[name]=base.completed_evaluation(directory,run,checkpoint,device,conf)
    verify(run)
    dump(output/'comparison.json',dict(conf=conf,models=results,deployment_benchmark='not_run'))
    lines=['# E06/KD1 同口径 Val 对照','',f'conf={conf}，完整Val1223张；Test未访问。','',
           '|模型|mAP50|mAP50-95|Recall|Small Recall|Occluded Recall|无球FPR|','|---|---:|---:|---:|---:|---:|---:|']
    for name,result in results.items():
        m=result['metrics'];s=result['scene_metrics']
        values=[m['mAP50'],m['mAP50_95'],m['recall'],s['Small']['recall'],s['Occluded']['recall'],m['no_ball_false_positive_rate']]
        lines.append('|'+name+'|'+'|'.join(f'{v*100:.3f}%' for v in values)+'|')
    lines+=['','E05/E06使用同一学生初始化和训练配方，E06增加冻结E01教师与特征蒸馏。',
            '单seed开发实验，早停轮数可能不同；没有机器人Hz或定位结论。']
    (output/'COMPARISON.md').write_text('\n'.join(lines)+'\n');print(output/'COMPARISON.md')


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=('prepare','smoke','train','verify','evaluate','status'))
    p.add_argument('--run');p.add_argument('--resume',action='store_true');p.add_argument('--dry-run',action='store_true')
    p.add_argument('--device',default='0');p.add_argument('--conf',type=float,choices=(.25,.45),default=.45)
    a=p.parse_args()
    if a.stage=='prepare':prepare();return
    run=run_path(a.run)
    if a.stage=='smoke':smoke(run)
    elif a.stage=='train':train(run,a.resume,a.dry_run)
    elif a.stage=='verify':print(json.dumps(verify(run),ensure_ascii=False,indent=2))
    elif a.stage=='evaluate':evaluate(run,a.device,a.conf)
    else:
        record=load(run/'run_record.json')
        print(f"运行：{run}\n状态：{record['status']}；正式训练已启动：{record['training_started']}")
        if (run/'preflight.json').exists():print('蒸馏冒烟：'+load(run/'preflight.json')['status'])
        if (run/'progress.json').exists():print(json.dumps(load(run/'progress.json'),ensure_ascii=False,indent=2))
        if record.get('error'):print('错误：'+record['error'])


if __name__=='__main__':main()
