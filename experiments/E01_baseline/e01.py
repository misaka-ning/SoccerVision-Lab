#!/usr/bin/env python3
"""E01 orchestration; reuse the shared config loader, trainer and Val evaluator."""
from __future__ import annotations

import argparse
import contextlib
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import io
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
DATA = ROOT / "datasets/v1"
WEIGHTS = ROOT / "baseline/E0_original_best.pt"
GPU_PYTHON = "/home/misaka/.local/share/vision-studio/gpu-runtime/bin/python"
CPU_PYTHON = "/opt/VisionStudio/runtime/bin/python"


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def command(args):
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    return dict(argv=args, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def environment(run):
    # Set these before importing torch/Ultralytics. Never install/download dependencies.
    os.environ.update(YOLO_OFFLINE="true", YOLO_AUTOINSTALL="false",
                      YOLO_CONFIG_DIR=str(run / "runtime/yolo"),
                      MPLCONFIGDIR=str(run / "runtime/matplotlib"),
                      OMP_NUM_THREADS="4", MKL_NUM_THREADS="4",
                      OPENBLAS_NUM_THREADS="4", CUBLAS_WORKSPACE_CONFIG=":4096:8")
    import torch
    torch.set_num_threads(4)


def read_record(run):
    return json.loads((run / "run_record.json").read_text())


def verify_inputs(run):
    expected = json.loads((run / "input_fingerprints.json").read_text())
    for p, value in expected.items():
        if sha(p) != value:
            raise RuntimeError(f"Protected input changed: {p}")
    return dict(checked_files=len(expected), unchanged=True, checked_utc=now(),
                test_pixels_or_labels_opened=False)


def prepare():
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_s42_" + uuid4().hex[:6]
    run = HERE / "runs" / run_id
    run.mkdir(parents=True, exist_ok=False)
    environment(run)
    import yaml
    import torch
    from PIL import Image
    import ultralytics
    from ultralytics import YOLO
    from ultralytics.models.yolo.detect import DetectionTrainer
    from ultralytics.utils.torch_utils import get_flops, init_seeds
    sys.path.insert(0, str(ROOT / "script/model-evaluation"))
    from dataset_io import select

    record = json.loads((ROOT / "experiments/_template/run_record.json").read_text())
    record.update(template_only=False, experiment_id=HERE.name, run_id=run_id,
                  status="preparing", created_utc=now())
    dump(run / "run_record.json", record)
    fingerprints = {str(p): sha(p) for p in [WEIGHTS, ROOT / "baseline/original_model.yaml",
                    DATA / "manifest.csv", DATA / "manifest.json", DATA / "metadata.csv",
                    DATA / "dataset.yaml", ROOT / "script/config.yaml",
                    ROOT / "experiments/configs/datasets/v1.dataset.yaml", *sorted((DATA / "lists").glob("*.txt"))]}
    src = [Path(__file__).resolve(), ROOT / "script/model-training/train.py",
           ROOT / "script/model-training/config/train.yaml", ROOT / "script/common/dataset_config.py",
           *sorted((ROOT / "script/model-evaluation").glob("*.py"))]
    git_status = command(["git", "status", "--porcelain=v1", "-uno"])
    (run / "source_status.txt").write_text(git_status["stdout"])
    # The worktree contains a large pre-existing dataset relocation. Snapshot
    # source changes only; dataset contents have their own frozen fingerprints.
    diff = subprocess.check_output(["git", "diff", "--no-ext-diff", "--no-textconv", "--",
                                    ":(exclude)datasets/**"], cwd=ROOT)
    record["source"].update(commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                            dirty=bool(git_status["stdout"]), diff_sha256=hashlib.sha256(diff).hexdigest(),
                            diff_scope="tracked files excluding datasets/**; see data fingerprints and source_status.txt",
                            script_hashes={str(p.relative_to(ROOT)): sha(p) for p in src})
    gpu = command(["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader"])
    env = dict(python=sys.version, executable=sys.executable, platform=platform.platform(),
               pytorch=torch.__version__, ultralytics=ultralytics.__version__, cuda=torch.version.cuda,
               cudnn=torch.backends.cudnn.version(), cuda_available=torch.cuda.is_available(),
               gpu_probe=gpu, cpu=command(["lscpu"]), memory=command(["free", "-h"]),
               dependencies={d.metadata["Name"]: d.version for d in importlib.metadata.distributions()})
    if torch.cuda.is_available():
        env.update(gpu=torch.cuda.get_device_name(0), gpu_total_bytes=torch.cuda.get_device_properties(0).total_memory,
                   gpu_free_bytes=torch.cuda.mem_get_info()[0])
    dump(run / "environment.json", env)
    record["environment"].update({k: env.get(k) for k in ("python", "ultralytics", "pytorch", "cuda", "cudnn")})
    record["environment"].update(gpu=env.get("gpu"), driver=gpu["stdout"].strip(), dependencies_ref="environment.json")

    # A file-symlink view preserves every member; all caches stay under this run.
    # Directory symlinks are deliberately avoided: check_det_dataset resolves them.
    view = run / "runtime/dataset"
    selections = {}
    rows = list(csv.DictReader((DATA / "manifest.csv").open(encoding="utf-8-sig", newline="")))
    manifest = {r["filename"]: r for r in rows}
    data_cfg = dict(path=str(view), train="images/train", val="images/val", nc=1,
                    names={0: "football"}, channels=3)
    frozen_cfg = yaml.safe_load((ROOT / "experiments/configs/datasets/v1.dataset.yaml").read_text())
    assert frozen_cfg["nc"] == 1 and frozen_cfg["names"] == {0: "football"}
    stats = {}
    for split, count in (("train", 4346), ("val", 1223)):
        selection = select(ROOT / "experiments/configs/datasets/v1.dataset.yaml", split)
        assert len(selection.samples) == count and not selection.skipped
        selections[split] = selection
        for kind in ("images", "labels"):
            (view / kind / split).mkdir(parents=True)
        for sample in selection.samples:
            assert sample.image.parent == DATA / "images" / split
            r = manifest[sample.image.name]
            assert r["usage"] == split
            assert sample.hashes["image_sha256"] == r["image_sha256"]
            assert sample.hashes["label_sha256"] == r["label_sha256"]
            # Refuse the JPEG repair path in Ultralytics before it can write.
            with Image.open(sample.image) as im:
                assert im.mode == "RGB", (sample.image, im.mode)
                if im.format == "JPEG":
                    with sample.image.open("rb") as f:
                        f.seek(-2, 2)
                        assert f.read() == b"\xff\xd9", f"JPEG would require repair: {sample.image}"
                im.load()
            for kind, source in (("images", sample.image), ("labels", sample.label)):
                (view / kind / split / source.name).symlink_to(source)
                fingerprints[str(source)] = sample.hashes["image_sha256" if kind == "images" else "label_sha256"]
        stats[split] = dict(images=len(selection.samples), boxes=sum(len(s.gt) for s in selection.samples),
                            no_ball_images=sum(not s.gt for s in selection.samples),
                            channels=[3], label_class_ids=[0], skipped=0)
    assert not (view / "images/test").exists() and "test" not in data_cfg
    (run / "dataset.train-val.yaml").write_text(yaml.safe_dump(data_cfg, sort_keys=False))
    (run / "dataset.val-evaluation.yaml").write_text(yaml.safe_dump(dict(path=str(DATA), train="images/train",
                       val="images/val", nc=1, names={0: "football"}), sort_keys=False))
    dump(run / "input_fingerprints.json", fingerprints)
    # Match every Val image, GT and scenario to E00, without rerunning E00.
    e00 = json.loads((ROOT / "experiments/E00_original/evaluation/inputs_manifest.json").read_text())
    assert e00["selected"] == [s.manifest() for s in selections["val"].samples]
    assert e00["model_sha256"] == fingerprints[str(WEIGHTS)]

    config = yaml.safe_load((ROOT / "script/model-training/config/train.yaml").read_text())
    config.update(model=str(WEIGHTS), data=str(run / "dataset.train-val.yaml"), project=str(run),
                  name="train", exist_ok=False, epochs=100, patience=30, batch=8, device="0",
                  workers=4, pretrained=True, freeze=None, nms=True, conf=0.001, iou=0.7,
                  max_det=300, rect=False, single_cls=False, fraction=1.0, save_period=10,
                  warmup_bias_lr=0.0, cutmix=0.0, copy_paste=0.0, multi_scale=0.0,
                  compile=False, channels_last=False)
    # AdamW starts at lr0=1e-3; avoid the SGD-oriented default bias warmup of 0.1.
    (run / "train.requested.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    shared = module("e01_shared_train", ROOT / "script/model-training/train.py")
    model_path, args = shared.build_plan(shared.parse_args(["--config", str(run / "train.requested.yaml")]))
    trainer = DetectionTrainer(overrides=dict(args, model=model_path, project=str(run / "precheck"), name="setup"))
    init_seeds(42, deterministic=True)
    old = YOLO(str(WEIGHTS)).model
    original_yaml = deepcopy(old.yaml)
    (run / "original.architecture.yaml").write_text(yaml.safe_dump(original_yaml, sort_keys=False))
    old_sd = {k: v.clone() for k, v in old.state_dict().items()}
    output = io.StringIO()
    # Use the exact official get_model/load path, with a deep copy of source cfg.
    new = trainer.get_model(cfg=deepcopy(original_yaml), weights=old, verbose=False)
    new_sd = new.state_dict()
    matched, reset = [], []
    for k, v in new_sd.items():
        if k in old_sd and v.shape == old_sd[k].shape:
            assert torch.equal(v, old_sd[k]), k
            matched.append(dict(key=k, shape=list(v.shape), elements=v.numel()))
        else:
            reset.append(dict(key=k, old_shape=list(old_sd[k].shape) if k in old_sd else None,
                              new_shape=list(v.shape), elements=v.numel()))
    assert len(old.names) == 80 and old.names[32] == "sports ball"
    assert new.model[-1].nc == 1 and new.names == {0: "football"}
    assert len(reset) == 12 and all("cv3" in r["key"] and r["key"].endswith(("2.weight", "2.bias")) for r in reset)
    groups = {}
    for item in matched:
        k = item["key"]
        layer = int(k.split(".")[1])
        group = "backbone" if layer <= 10 else "neck" if layer < 23 else "head_regression" if "cv2" in k else "head_classification_features"
        groups.setdefault(group, dict(tensors=0, elements=0))
        groups[group]["tensors"] += 1
        groups[group]["elements"] += item["elements"]
    transfer = dict(source_nc=80, target_nc=1, source_tensor_count=len(old_sd), target_tensor_count=len(new_sd),
                    transferred_tensor_count=len(matched), reinitialized_tensor_count=len(reset),
                    source_parameters=sum(p.numel() for p in old.parameters()),
                    target_parameters=sum(p.numel() for p in new.parameters()),
                    matched=matched, reinitialized=reset, unexpected_keys=sorted(set(old_sd) - set(new_sd)),
                    groups=groups, source_inference_end2end=old.end2end,
                    target_constructor_end2end=new.end2end, inference_nms=True, reg_max=new.model[-1].reg_max,
                    classification_outputs={a: [m[-1].out_channels for m in getattr(new.model[-1], a)] for a in ("cv3", "one2one_cv3")},
                    name_remap_applied=False, exact_value_comparison_before_training=True)
    dump(run / "transfer.json", transfer)
    (run / "transfer.log").write_text(f"Official DetectionTrainer.get_model -> DetectionModel.load\nTransferred {len(matched)}/{len(new_sd)} state_dict tensors; {len(reset)} shape mismatches.\nAll compatible tensors exactly equal before training.\n")
    (run / "single-class.architecture.yaml").write_text(yaml.safe_dump(new.yaml, sort_keys=False))
    record["initialization"].update(mode="official_compatible_weight_transfer", path=str(WEIGHTS), sha256=sha(WEIGHTS),
        compatible_tensor_count=len(matched), total_tensor_count=len(new_sd), missing_keys=[r["key"] for r in reset],
        unexpected_keys=transfer["unexpected_keys"], newly_initialized_modules=[r["key"] for r in reset],
        exposure=dict(evidence_ref="user request / reports/workspace-organization/OWNER_ASSERTIONS.md",
                      current_test_seen=False, some_training_images_seen=True, unknown_details=[]))
    record["architecture"].update(file="single-class.architecture.yaml", sha256=sha(run / "single-class.architecture.yaml"),
        variant="YOLO26s", class_count=1, output_strides=[8, 16, 32], parameter_count=transfer["target_parameters"])
    record["data"].update(version="v1", shared_config_sha256=sha(ROOT / "script/config.yaml"),
        resolved_runtime_yaml_sha256=sha(run / "dataset.train-val.yaml"), metadata_sha256=sha(DATA / "metadata.csv"),
        frozen_manifest_sha256=sha(DATA / "manifest.csv"), manifest_json_sha256=sha(DATA / "manifest.json"),
        split_list_sha256={p.stem: sha(p) for p in (DATA / "lists").glob("*.txt")},
        image_label_content_manifest_sha256=sha(run / "input_fingerprints.json"),
        counts=dict(train=4346, val=1223, test=464, buffer=755, heldout_unused=1360),
        relation="Val same-session-independent source; Test same-session segment holdout; Test content not read")
    record["training"].update(enabled=True, config_ref="train.requested.yaml", config_sha256=sha(run / "train.requested.yaml"),
        seed=42, deterministic=True, device="0", best_selection_rule="official Val fitness (mAP50-95 in this version)",
        actual_output_ref=str(run / "train"), best_checkpoint_ref=None, last_checkpoint_ref=None)
    record["evaluation"].update(class_mapping={"E00": 32, "E01": 0}, imgsz=640, letterbox_rect=False,
        min_conf=0.001, operating_conf=0.25, match_iou=0.5, nms_iou=0.7, max_det=300, end_to_end_head=False)
    precheck = dict(status="data_and_transfer_passed", data=stats, val_matches_e00=True, test_path_absent=True,
                    model_nc=1, names=new.names, requested_batch=8, cuda_available=torch.cuda.is_available())
    dump(run / "precheck.json", precheck)
    dump(run / "run_record.json", record)
    smoke(run)
    print(f"E01_RUN={run}", flush=True)
    return run


def smoke(run):
    environment(run)
    import torch
    import yaml
    from ultralytics import YOLO
    from ultralytics.models.yolo.detect import DetectionTrainer
    from ultralytics.utils.torch_utils import init_seeds
    record = read_record(run)
    assert record["status"] in ("preparing", "precheck_failed")
    precheck = json.loads((run / "precheck.json").read_text())
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable: run preparation under the GPU-enabled host environment")
    cfg = yaml.safe_load((run / "train.requested.yaml").read_text())
    cfg.update(project=str(run / "precheck"), name="setup")
    trainer = DetectionTrainer(overrides=cfg)
    init_seeds(42, deterministic=True)
    old = YOLO(str(WEIGHTS)).model
    new = trainer.get_model(cfg=deepcopy(old.yaml), weights=old, verbose=False)
    # Real official dataset, 640px batch, loss, AMP backward and optimizer step.
    trainer.model = new.to("cuda")
    trainer.set_model_attributes()
    train_ds = trainer.build_dataset(trainer.data["train"], mode="train", batch=8)
    val_ds = trainer.build_dataset(trainer.data["val"], mode="val", batch=8)
    assert len(train_ds) == 4346 and len(val_ds) == 1223
    batch = train_ds.collate_fn([train_ds[i] for i in range(8)])
    batch = {k: v.to("cuda") if isinstance(v, torch.Tensor) else v for k, v in batch.items()}
    batch["img"] = batch["img"].float() / 255
    assert batch["img"].shape == (8, 3, 640, 640) and set(batch["cls"].flatten().tolist()) <= {0.0}
    new.train()
    torch.cuda.reset_peak_memory_stats()
    optimizer = torch.optim.AdamW(new.parameters(), lr=0.001)
    scaler = torch.amp.GradScaler("cuda")
    start = time.perf_counter()
    scale_checks = []
    for attempt in range(12):
        optimizer.zero_grad(set_to_none=True)
        with torch.amp.autocast("cuda"):
            loss, items = new(batch)
        assert torch.isfinite(loss).all() and all(torch.isfinite(v).all() for v in items.values())
        scaler.scale(loss.sum()).backward()
        scaler.unscale_(optimizer)
        finite = all(torch.isfinite(p.grad).all() for p in new.parameters() if p.grad is not None)
        scale_checks.append(dict(attempt=attempt + 1, scale=scaler.get_scale(), finite_gradients=finite))
        # Native GradScaler skips an overflowing step and automatically lowers
        # its scale. This is ordinary AMP startup, not a hyperparameter change.
        scaler.step(optimizer)
        scaler.update()
        if finite:
            break
    assert finite, scale_checks
    torch.cuda.synchronize()
    precheck.update(status="passed", input_shape=list(batch["img"].shape), amp_loss=loss.detach().cpu().tolist(),
        loss_components={k: v.detach().cpu().tolist() for k, v in items.items()}, finite_gradients=True, optimizer_step=True,
        batch_step_seconds=time.perf_counter() - start, peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
        peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved(), gpu_free_after_bytes=torch.cuda.mem_get_info()[0],
        amp_scale_checks=scale_checks, formal_checkpoint_reuses_smoke_state=False)
    # Precheck weights are deliberately not saved; formal run reinitializes from baseline.
    dump(run / "precheck.json", precheck)
    dump(run / "input_integrity.after_precheck.json", verify_inputs(run))
    record.update(status="prechecked")
    dump(run / "run_record.json", record)
    print(json.dumps(precheck, ensure_ascii=False), flush=True)


def train(run, resume=False):
    environment(run)
    import torch
    import yaml
    from ultralytics import YOLO
    shared = module("e01_shared_train", ROOT / "script/model-training/train.py")
    record = read_record(run)
    assert record["status"] in ("prechecked", "training_failed", "training")
    verify_inputs(run)
    record["source"]["training_entry_sha256"] = sha(__file__)
    shutil.copy2(__file__, run / "e01.executed.py")
    cfg = run / "train.requested.yaml"
    out = run / "train"
    if not resume and out.exists():
        raise FileExistsError(out)
    source = out / "weights/resume-last.pt" if resume else WEIGHTS
    if resume:
        ckpt = torch.load(source, map_location="cpu", weights_only=False)
        assert ckpt["optimizer"] is not None and ckpt["epoch"] >= 0
        record["training"]["resume_events"].append(dict(utc=now(), path=str(source), sha256=sha(source)))
        args = dict(resume=str(source), device="0")
    else:
        _, args = shared.build_plan(shared.parse_args(["--config", str(cfg)]))
    model = YOLO(str(source), task="detect")

    def ready(t):
        assert t.model.model[-1].nc == 1 and t.model.names == {0: "football"}
        assert len(t.train_loader.dataset) == 4346 and len(t.test_loader.dataset) == 1223
        assert "test" not in t.data or not t.data["test"]
        # The live training module runs both heads; validator selects the EMA
        # inference branch when it first runs (after this callback).
        assert t.args.nms is True and t.validator.args.nms is True
        if not resume:
            baseline_sd = YOLO(str(WEIGHTS)).model.state_dict()
            current_sd = t.model.state_dict()
            expected = json.loads((run / "transfer.json").read_text())["matched"]
            assert all(torch.equal(current_sd[v["key"]].cpu(), baseline_sd[v["key"]]) for v in expected)
            dump(run / "transfer.formal.json", dict(utc=now(), compatible_tensors_verified=len(expected),
                 all_exact_before_first_gradient_step=True, source_sha256=sha(WEIGHTS), nc=1))
        dump(run / "train.effective.json", vars(t.args))
        optimizer = dict(class_name=type(t.optimizer).__name__, groups=[{k: v for k, v in g.items() if k != "params"} for g in t.optimizer.param_groups],
                         amp=t.amp, accumulate=t.accumulate, train_images=len(t.train_loader.dataset), val_images=len(t.test_loader.dataset),
                         training_model_end2end=t.model.end2end, validation_inference_end2end=False)
        dump(run / "optimizer.effective.json", optimizer)
        record["training"]["effective_args"] = vars(t.args).copy()
        record["training"]["started_utc"] = now()
        dump(run / "run_record.json", record)

    def saved(t):
        # Official final_eval strips optimizer from best/last. Keep a real resume copy.
        if t.last.exists():
            shutil.copy2(t.last, t.wdir / "resume-last.pt")

    def epoch(t):
        if getattr(t, "metrics", None):
            dump(run / "progress.json", dict(utc=now(), epoch=t.epoch + 1, epochs=t.epochs,
                 metrics=t.metrics, fitness=t.fitness, best_fitness=t.best_fitness,
                 gpu_peak_allocated_bytes=torch.cuda.max_memory_allocated()))

    model.add_callback("on_pretrain_routine_end", ready)
    model.add_callback("on_model_save", saved)
    model.add_callback("on_fit_epoch_end", epoch)
    record.update(status="training")
    dump(run / "run_record.json", record)
    start = time.perf_counter()
    try:
        model.train(**args)
        assert model.trainer.save_dir == out
        record.update(status="trained", completed_utc=now())
        record["training"].update(elapsed_seconds=time.perf_counter() - start,
            best_checkpoint_ref=str(out / "weights/best.pt"), last_checkpoint_ref=str(out / "weights/last.pt"),
            resume_checkpoint_ref=str(out / "weights/resume-last.pt"),
            checkpoint_sha256={k: sha(out / f"weights/{k}.pt") for k in ("best", "last")},
            results_csv_ref=str(out / "results.csv"))
    except BaseException as exc:
        record.update(status="training_failed")
        record["result"]["failure_reason"] = repr(exc)
        raise
    finally:
        dump(run / "run_record.json", record)
        dump(run / "input_integrity.after_training.json", verify_inputs(run))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["prepare", "smoke", "train", "resume", "verify"])
    p.add_argument("--run", type=Path)
    a = p.parse_args()
    if a.stage == "prepare":
        prepare()
    else:
        assert a.run is not None
        run = a.run.resolve()
        assert run.parent == HERE / "runs"
        if a.stage == "smoke":
            smoke(run)
        elif a.stage == "verify":
            dump(run / "input_integrity.final.json", verify_inputs(run))
        else:
            train(run, resume=a.stage == "resume")


if __name__ == "__main__":
    main()
