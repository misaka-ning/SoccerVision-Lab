#!/usr/bin/env python3
"""Independent checkpoint verification and identically bounded E00/E01 profiling."""
import argparse
from copy import deepcopy
import importlib.metadata
import json
from pathlib import Path
import time

from e01 import ROOT, DATA, WEIGHTS, dump, environment, now, sha


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True, type=Path)
    a = p.parse_args()
    run = a.run.resolve()
    environment(run)
    import numpy as np
    import torch
    from ultralytics import YOLO
    from ultralytics.utils.torch_utils import get_flops
    best = run / "train/weights/best.pt"
    checkpoints = {}
    for tag in ("best", "last", "resume-last"):
        path = run / f"train/weights/{tag}.pt"
        ckpt = torch.load(path, map_location="cpu", weights_only=False)
        net = ckpt.get("ema") or ckpt.get("model")
        assert net.model[-1].nc == 1 and net.names == {0: "football"}
        checkpoints[tag] = dict(path=str(path), sha256=sha(path), bytes=path.stat().st_size,
            epoch=ckpt["epoch"], nc=net.model[-1].nc, names=net.names,
            optimizer_present=ckpt.get("optimizer") is not None, scaler_present=bool(ckpt.get("scaler")),
            training_metrics=ckpt.get("train_metrics"))
        if tag == "resume-last":
            assert ckpt["epoch"] >= 0 and ckpt.get("optimizer") is not None
        del net, ckpt
    dump(run / "checkpoint_audit.json", checkpoints)
    model = YOLO(str(best))
    h = model.model.model[-1]
    assert model.names == {0: "football"} and len(model.names) == 1 and h.nc == 1
    dims = {attr: [m[-1].out_channels for m in getattr(h, attr)] for attr in ("cv3", "one2one_cv3")}
    assert all(v == [1, 1, 1] for v in dims.values())
    # No classes filter: out-of-range detections cannot be hidden by filtering.
    reference = json.loads((ROOT / "experiments/E00_original/evaluation/inputs_manifest.json").read_text())
    images = [Path(s["image"]) for s in reference["selected"] if s["gt_boxes"] > 0][:16]
    assert len(images) == 16 and all(p.parent == DATA / "images/val" for p in images)
    predictions = model.predict([str(p) for p in images], imgsz=640, rect=False, batch=4,
        device="0", conf=0.001, iou=0.7, max_det=300, nms=True, verbose=False)
    observed = sorted({int(c) for r in predictions for c in r.boxes.cls.cpu().tolist()})
    assert observed == [0]
    raw_model = YOLO(str(best)).model.cuda().eval()
    with torch.inference_mode():
        y = raw_model(torch.zeros(1, 3, 640, 640, device="cuda"))[0]
    assert list(y.shape) == [1, 5, 8400]
    dump(run / "single_class_verification.json", dict(utc=now(), checkpoint=str(best), sha256=sha(best),
         independent_reload=True, names=model.names, names_count=1, head_nc=h.nc, classification_output_dimensions=dims,
         raw_output_shape=list(y.shape), class_channels=1, inference_images=len(images),
         inference_source="v1 Val only", observed_class_ids=observed, prediction_class_filter=None, passed=True))
    del model, raw_model, predictions
    torch.cuda.empty_cache()
    rows = {}
    for name, path in (("E00", WEIGHTS), ("E01", best)):
        m = YOLO(str(path)).model.float().eval()
        parameters = sum(p.numel() for p in m.parameters())
        # Profiling unfused counts both stored branches; deployment removes the
        # unused branch via the same official fuse() used by AutoBackend.
        unfused_flops = get_flops(deepcopy(m), imgsz=640)
        m.end2end = False
        m.fuse(verbose=False)
        fused_parameters = sum(p.numel() for p in m.parameters())
        fused_flops = get_flops(deepcopy(m), imgsz=640)
        assert unfused_flops > 0 and fused_flops > 0
        m.cuda()
        torch.cuda.empty_cache()
        x = torch.rand(1, 3, 640, 640, device="cuda")
        # Explicit FP32 and identical layout. GPU events exclude host scheduling.
        torch.backends.cudnn.benchmark = False
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        wall, gpu = [], []
        with torch.inference_mode():
            raw_shape = list(m(x)[0].shape)
            for _ in range(20):
                m(x)
            torch.cuda.synchronize()
            for _ in range(100):
                start_event, stop_event = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
                start = time.perf_counter()
                start_event.record()
                m(x)
                stop_event.record()
                stop_event.synchronize()
                wall.append((time.perf_counter() - start) * 1000)
                gpu.append(start_event.elapsed_time(stop_event))
        summary = lambda v: dict(mean=float(np.mean(v)), p50=float(np.percentile(v, 50)), p95=float(np.percentile(v, 95)))
        rows[name] = dict(path=str(path), sha256=sha(path), file_bytes=path.stat().st_size, nc=len(m.names),
            classification_output_channels=m.model[-1].nc, raw_output_shape=raw_shape,
            stored_parameters=parameters, fused_selected_branch_parameters=fused_parameters,
            unfused_both_branch_gflops=unfused_flops, fused_selected_branch_gflops=fused_flops,
            cuda_event_latency_ms=summary(gpu), synchronized_wall_latency_ms=summary(wall))
        del m, x
        torch.cuda.empty_cache()
    dump(run / "model_comparison.json", dict(utc=now(), models=rows, gpu=torch.cuda.get_device_name(0),
         torch=torch.__version__, cuda=torch.version.cuda, precision="FP32; TF32 disabled",
         ultralytics=importlib.metadata.version("ultralytics"), thop=importlib.metadata.version("ultralytics-thop"),
         input_shape=[1, 3, 640, 640], warmup=20, timed=100,
         timing_boundary="fused one-to-many model forward including box decode; excludes preprocessing, H2D, NMS, file I/O",
         synchronization="CUDA events plus stop_event.synchronize each repetition; wall includes host dispatch",
         flops_method="Ultralytics get_flops / THOP stride-aware profiling; MAC*2; includes head; excludes NMS and preprocessing",
         cpu_latency_reference="Full Val evaluator reports CPU single-thread batch4 timing for both models; not deployment benchmark",
         orin_tensorrt_measured=False))


if __name__ == "__main__":
    main()
