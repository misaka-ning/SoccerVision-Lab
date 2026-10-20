#!/usr/bin/env python3
"""Evaluate a local Ultralytics football detector on reviewed YOLO data."""
from __future__ import annotations
import argparse
import contextlib
from datetime import datetime, timezone
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]


def parse_args(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',required=True,help='本地.pt/.onnx/.engine/.torchscript文件；相对仓库根目录')
    p.add_argument('--data',help='显式覆盖数据集YAML；默认读取script/config.yaml所选版本')
    p.add_argument('--dataset-config',help='覆盖共享数据集配置，相对仓库根目录')
    p.add_argument('--dataset-version',help='本次覆盖v0/v1等版本，不修改共享配置')
    p.add_argument('--metadata',help='审核metadata.csv，默认在数据集根目录')
    p.add_argument('--split',choices=('val','test','train'),default='val')
    p.add_argument('--class-id',type=int,help='模型中的足球类别ID；多类模型必须显式指定，例如COCO为32')
    p.add_argument('--imgsz',type=int,default=640)
    p.add_argument('--batch',type=int,default=4)
    p.add_argument('--device',help='cpu或GPU编号；不指定时由Ultralytics选择')
    p.add_argument('--threads',type=int,default=1,help='CPU计算线程数，默认1')
    p.add_argument('--min-conf',type=float,default=.001,help='保留用于AP/P-R的最低候选分数')
    p.add_argument('--conf',type=float,default=.25,help='固定工作阈值，用于P/R/F1/无球FPR')
    p.add_argument('--match-iou',type=float,default=.5,help='固定工作指标的匹配IoU，不改变AP的10个IoU')
    p.add_argument('--nms-iou',type=float,default=.7)
    p.add_argument('--max-det',type=int,default=300)
    p.add_argument('--limit',type=int,help='仅调试：按文件名取前N张，结果标记为部分集合')
    p.add_argument('--output',help='新建输出目录，相对仓库根目录；已存在则拒绝覆盖')
    p.add_argument('--formats',default='png',help='图表格式，默认仅png；可指定svg、pdf或逗号分隔的多个格式')
    p.add_argument('--dpi',type=int,default=300)
    p.add_argument('--dry-run',action='store_true',help='只检查选择/审核/label；可生成共享运行YAML，不加载模型、不创建评估结果目录')
    a=p.parse_args(argv)
    for key in ('imgsz','batch','threads','max_det','dpi'):
        if getattr(a,key)<=0:p.error(f'{key}须为正整数')
    if a.limit is not None and a.limit<=0:p.error('limit须为正整数')
    if not all(math.isfinite(v) for v in (a.min_conf,a.conf,a.match_iou,a.nms_iou)) or not 0<a.min_conf<=a.conf<=1 or not 0<a.match_iou<=1 or not 0<a.nms_iou<=1:
        p.error('阈值须为有限数，0 < min-conf <= conf <= 1，IoU在(0,1]内')
    if a.class_id is not None and a.class_id<0:p.error('class-id须非负')
    if not a.formats or any(v not in ('png','pdf','svg') for v in a.formats.split(',')):p.error('formats只支持png,pdf,svg')
    return a


def choose_class(names, requested):
    names=dict(enumerate(names)) if isinstance(names,list) else {int(k):v for k,v in names.items()}
    if requested is None:
        if len(names)!=1:
            raise ValueError(f'模型有{len(names)}个类别，请显式指定 --class-id；原参考COCO权重足球为32，0为person。')
        return next(iter(names))
    if requested not in names:raise ValueError(f'模型没有类别ID {requested}，可用类别：{names}')
    return requested


def main(argv=None):
    args=parse_args(argv)
    # Set before importing numpy/torch/Ultralytics; do not auto-install missing runtimes.
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[name]=str(args.threads)
    os.environ['YOLO_AUTOINSTALL']='false'
    os.environ['YOLO_OFFLINE']='true'
    out=None
    try:
        from dataset_io import resolve_path,select,digest,assert_unchanged
        model_path=resolve_path(args.model,ROOT)
        if not model_path.is_file() or model_path.suffix.lower() not in ('.pt','.onnx','.engine','.torchscript'):
            raise ValueError(f'请输入已存在的本地检测权重.pt/.onnx/.engine/.torchscript：{model_path}')
        if args.data is None:
            sys.path.insert(0,str(ROOT/'script'))
            from common.dataset_config import load_dataset,materialize_yaml
            selected=load_dataset(args.dataset_config,args.dataset_version,root=ROOT)
            data=materialize_yaml(selected)
            args.dataset_version=selected['version']
            args.dataset_config=str(selected['config'])
            print(f'数据版本：{selected["version"]}；目录：{selected["root"]}',flush=True)
        else:
            if args.dataset_config or args.dataset_version:
                raise ValueError('--data显式覆盖不能与--dataset-config/--dataset-version同时使用。')
            data=resolve_path(args.data,ROOT)
        metadata=resolve_path(args.metadata,ROOT) if args.metadata else None
        selection=select(data,args.split,metadata,args.limit)
        args.output=args.output or 'experiments/eval/'+model_path.stem+'_'+args.split+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:6]
        planned_out=resolve_path(args.output,ROOT)
        if planned_out.exists() or planned_out==selection.root or selection.root in planned_out.parents:
            raise ValueError('输出目录须在原数据集之外且尚不存在，避免覆盖或污染数据。')
        print(f'集合{args.split}：{len(selection.samples)}/{selection.available_before_limit}张可用图；跳过{len(selection.skipped)}张。',flush=True)
        print(f'模型：{model_path}\n结果目录：{planned_out}',flush=True)
        if args.dry_run:
            assert_unchanged(selection)
            print('预检查通过。未加载模型、未检验类别/设备兼容性，未创建评估结果目录；共享运行YAML可能已生成。')
            return 0
        # Keep Ultralytics settings outside the source dataset and source tree.
        planned_out.mkdir(parents=True,exist_ok=False)
        out=planned_out
        (out/'status.json').write_text('{"status":"running"}\n')
        runtime_dir=out/'.runtime-config'
        runtime_dir.mkdir()
        os.environ['YOLO_CONFIG_DIR']=str(out/'.runtime-config/yolo')
        os.environ['MPLCONFIGDIR']=str(out/'.runtime-config/matplotlib')
        import numpy as np
        import torch
        torch.set_num_threads(args.threads)
        from ultralytics import YOLO
        from eval_metrics import prepare,operating,summarize,groups
        from reporting import save_report
        np.random.seed(42);torch.manual_seed(42)
        model_hash=digest(model_path)
        model=YOLO(str(model_path),task='detect')
        if model.task!='detect':raise ValueError('只支持detect模型，不把分割/分类/姿态结果当检测结果。')
        # CPU backend setup calls select_device(), which resets torch threads.
        # Restore the requested limit after setup and before warmup/inference.
        model.add_callback('on_predict_start',lambda predictor:torch.set_num_threads(args.threads))
        # Accessing .names on exported models can initialize a backend on the
        # default device before --device is applied. Validate exported names
        # from the first real prediction instead; PT names need no inference.
        names=model.names if model_path.suffix.lower()=='.pt' else None
        class_id=choose_class(names,args.class_id) if names is not None else args.class_id
        manifest=dict(model=str(model_path),model_sha256=model_hash,data=str(data),metadata=str(selection.metadata),
                      **selection.hashes,selected=[s.manifest() for s in selection.samples],skipped=selection.skipped,
                      arguments=vars(args),model_names=names,selected_model_class_id=class_id,
                      evaluation_code_sha256={p.name:digest(p) for p in Path(__file__).resolve().parent.glob('*.py')},
                      metrics_method='Ultralytics AP / highest-IoU greedy matching; fixed-threshold operating metrics')
        (out/'inputs_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        records=[];speeds=[];start=time.perf_counter()
        # A Python list of paths is eagerly converted into PIL/numpy images by
        # Ultralytics. A txt source uses the batch-streaming file loader instead.
        input_list=runtime_dir/'selected-images.txt'
        input_list.write_text(''.join(str(s.image)+'\n' for s in selection.samples),encoding='utf-8')
        predictions=model.predict(source=str(input_list),stream=True,
                                  imgsz=args.imgsz,batch=args.batch,device=args.device,
                                  conf=args.min_conf,iou=args.nms_iou,max_det=args.max_det,
                                  classes=[class_id] if class_id is not None else None,rect=False,augment=False,
                                  save=False,save_txt=False,verbose=False)
        with (out/'predictions.jsonl').open('w',encoding='utf-8') as stream,contextlib.closing(predictions):
            for i,result in enumerate(predictions):
                if i>=len(selection.samples):raise RuntimeError('推理返回多余图片结果。')
                sample=selection.samples[i]
                if i==0:
                    class_id=choose_class(result.names,args.class_id)
                    manifest.update(model_names=result.names,selected_model_class_id=class_id)
                    (out/'inputs_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
                if Path(result.path).resolve()!=sample.image:
                    raise RuntimeError('推理结果顺序与输入清单不同，拒绝错误配对。')
                if result.boxes is None:raise RuntimeError('模型未返回检测框结果，可能不是detect模型。')
                xyxy=result.boxes.xyxy.detach().cpu().numpy()
                scores=result.boxes.conf.detach().cpu().numpy()
                classes=result.boxes.cls.detach().cpu().numpy()
                keep=(classes==class_id)&(scores>=args.min_conf)
                xyxy,scores=xyxy[keep],scores[keep]
                if not np.isfinite(xyxy).all() or not np.isfinite(scores).all() or np.any((scores<0)|(scores>1)) or np.any(xyxy[:,2:]<=xyxy[:,:2]):
                    raise RuntimeError(f'模型输出非法坐标或分数：{sample.image}')
                if np.any(xyxy[:,:2]<-1e-3) or np.any(xyxy[:,2:]>np.array([sample.width,sample.height])+1e-3):
                    raise RuntimeError(f'模型输出坐标超出原图：{sample.image}')
                row=dict(image=str(sample.image),width=sample.width,height=sample.height,
                         gt=sample.gt,flags=sample.flags,boxes=xyxy.tolist(),scores=scores.tolist())
                stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n');records.append(row)
                speeds.append(result.speed)
                if (i+1)%100==0:print(f'已预测{i+1}/{len(selection.samples)}张',flush=True)
        elapsed=time.perf_counter()-start
        if len(records)!=len(selection.samples):raise RuntimeError('推理结果不完整，不能发布指标。')
        records=prepare(records)
        grouped=groups(records);group_metrics={};pr=None
        for name,subset in grouped.items():
            group_metrics[name],curve=summarize(subset,args.conf,args.match_iou)
            if name=='All':pr=curve
        thresholds=np.unique(np.r_[np.linspace(args.min_conf,1,101),args.conf])
        curves=[operating(records,float(c),args.match_iou) for c in thresholds]
        per_image=[]
        for record in records:
            m=operating([record],args.conf,args.match_iou)
            per_image.append(dict(image=record['image'],**{k:m[k] for k in ('gt_boxes','predicted_boxes','TP','FP','FN','precision','recall')},
                                  **record['flags'],max_candidate_confidence=float(max(record['scores'])) if len(record['scores']) else None))
        assert_unchanged(selection)
        if digest(model_path)!=model_hash:raise RuntimeError('评估期间模型文件变化，不能发布结果。')
        runtime=dict(predict_wall_seconds=elapsed,predict_images_per_second_including_warmup=len(records)/elapsed,
                     backend_reported_mean_ms={key:float(np.mean([r[key] for r in speeds if r.get(key) is not None])) for key in ('preprocess','inference','postprocess') if any(r.get(key) is not None for r in speeds)},
                     device=str(model.predictor.device),torch_threads=torch.get_num_threads(),
                     image_loader=type(model.predictor.dataset).__name__,
                     loader_batch_size=getattr(model.predictor.dataset,'bs',None),
                     actual_input_shape=[int(v) for v in model.predictor.imgsz],
                     backend_fp16=bool(getattr(model.predictor.model,'fp16',False)),
                     backend_end2end=bool(getattr(model.predictor.model,'end2end',False)))
        summary=dict(status='complete',model=str(model_path),model_name=model_path.stem,model_class_id=class_id,
                     split=args.split,partial_split=len(records)<selection.available_before_limit,
                     available_before_limit=selection.available_before_limit,skipped_images=len(selection.skipped),
                     metrics=group_metrics['All'],scene_metrics=group_metrics,runtime=runtime,
                     input_files_verified_unchanged=True,versions={k:importlib.metadata.version(k) for k in ('ultralytics','torch','numpy','matplotlib','PyYAML')},
                     created_at_utc=datetime.now(timezone.utc).isoformat(),arguments=vars(args))
        save_report(out,summary,group_metrics,curves,records,per_image,pr,args)
        (out/'status.json').write_text(json.dumps({'status':'complete','input_files_verified_unchanged':True})+'\n')
        import shutil
        shutil.rmtree(out/'.runtime-config',ignore_errors=True)
        m=summary['metrics'];print(f"mAP50={m['mAP50']}  mAP50-95={m['mAP50_95']}  Precision={m['precision']}  Recall={m['recall']}  No-ball FPR={m['no_ball_false_positive_rate']}")
        print(f'完成：{out}/REPORT.md')
        return 0
    except Exception as exc:
        if out is not None:
            (out/'status.json').write_text(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False)+'\n')
            (out/'error.log').write_text(traceback.format_exc())
        print(f'评估失败：{exc}',file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
