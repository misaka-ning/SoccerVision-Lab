#!/usr/bin/env python3
"""Single robot worker: event timing of the complete AutoBackend.forward boundary.

The coordinator owns serialization, source checks, power checks and A/B order.
execution_cuda_ms includes Graph input D2D update, replay, output clone and stream
waits. It is NOT the stage0/E03 execute_async_v2-only Engine CUDA-event metric.
No camera, ROS node, preprocessing, NMS or detection publication is timed here.
"""

import argparse
import csv
import ctypes
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import statistics
import sys
import time
import traceback


EXPECTED_ENGINE = "98c1b6bc703b29874d95db94d9cf51ef5b4a4142a7ca6cf22362a0c616fbf348"
INPUT_SHAPE = (2, 3, 640, 640)
OUTPUT_SHAPE = (2, 5, 8400)
FIELDS = ("sample", "elapsed_s", "execution_cuda_ms", "forward_call_wall_ms", "execution_complete_wall_ms")


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def parent_exit_protection(parent):
    """Linux PDEATHSIG and race check; never manipulate another process."""
    if parent <= 1:
        raise RuntimeError("An active coordinator parent is required")
    library = ctypes.CDLL(None, use_errno=True)
    if library.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Cannot establish parent-exit protection")
    if os.getppid() != parent:
        raise RuntimeError("Coordinator exited while enabling parent-exit protection")


def interrupted(signum, frame):
    raise KeyboardInterrupt("Worker interrupted by signal {}".format(signum))


def output_directory(run, output):
    run, output = Path(run).resolve(), Path(output).resolve()
    if not (run.parent.name == "E04_tensorrt_pipeline" or
            (run.parent.name == "runs" and run.parent.parent.name == "E04_tensorrt_pipeline")):
        raise ValueError("Expected the original E04_tensorrt_pipeline run directory")
    if run not in output.parents or output == run:
        raise ValueError("Output must be a new directory inside this E04 run")
    # Even a typo must not create a measurement directory in a frozen artifact.
    protected = {"frozen_models", "inputs", "collection_v1", "audit", "audit_extra", "scripts", "deployment_snapshot", "worktrees"}
    first = output.relative_to(run).parts[0]
    if first in protected or first.startswith("stage0_"):
        raise ValueError("Output cannot be inside protected baseline/model/input data")
    output.mkdir(parents=True, exist_ok=False)
    return run, output


def frozen_case(run):
    """Read only the original Val performance pair; no dataset search."""
    contract_path = run / "frozen_contract.json"
    contract = json.loads(contract_path.read_text())
    if contract["engine_sha256"] != EXPECTED_ENGINE:
        raise ValueError("Frozen contract does not identify the original E01 Engine")
    engine = run / "frozen_models/E01_baseline.engine"
    if digest(engine) != EXPECTED_ENGINE:
        raise ValueError("Frozen E01 Engine identity changed")
    manifest_path = run / "inputs/cases.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("split") != "val" or manifest.get("test_accessed") is not False:
        raise ValueError("Only frozen Val inputs are allowed")
    pair_key = manifest["performance_pair"]
    pair = next(p for p in manifest["pairs"] if p["pair_key"] == pair_key)
    if pair_key != "frame_001479":
        raise ValueError("Performance pair changed from the frozen E03/E04 pair")
    image_records = {x["name"]: x for x in manifest["images"]}
    images = []
    for eye in ("left", "right"):
        name = pair[eye]
        path = (run / "inputs/images" / name).resolve()
        if path.parent != (run / "inputs/images").resolve() or digest(path) != image_records[name]["image_sha256"]:
            raise ValueError("Frozen {} image changed".format(eye))
        images.append(path)
    reference = run / "stage0_golden_attempt1"
    golden_path = reference / "golden.json"
    golden = json.loads(golden_path.read_text())
    if golden.get("status") != "complete" or golden.get("split") != "val" or golden.get("test_accessed") is not False:
        raise ValueError("Expected the completed frozen stage0 Val Golden")
    if not any(x["pair_key"] == pair_key for x in golden["records"]):
        raise ValueError("Performance pair absent from frozen Golden")
    return {
        "contract": contract,
        "engine": engine,
        "images": images,
        "pair_key": pair_key,
        "npz": reference / (pair_key + ".npz"),
        "provenance": {
            "contract_sha256": digest(contract_path),
            "cases_sha256": digest(manifest_path),
            "golden_json_sha256": digest(golden_path),
            "golden_npz_sha256": digest(reference / (pair_key + ".npz")),
        },
    }


def summary(values):
    ordered = sorted(float(x) for x in values)
    if not ordered or any(not math.isfinite(x) or x < 0 for x in ordered):
        raise ValueError("Missing or invalid timing samples")

    def percentile(q):
        point = (len(ordered) - 1) * q
        lo, hi = math.floor(point), math.ceil(point)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (point - lo)

    return dict(samples=len(ordered), mean=statistics.mean(ordered), min=ordered[0],
                p50=percentile(.5), p95=percentile(.95), p99=percentile(.99), max=ordered[-1])


def resources(torch, device, label):
    """Outside timed calls; device free includes non-Torch TRT allocations."""
    result = dict(label=label, monotonic_s=time.monotonic(), pid=os.getpid(),
                  torch_allocated_bytes=int(torch.cuda.memory_allocated(device)),
                  torch_reserved_bytes=int(torch.cuda.memory_reserved(device)))
    free, total = torch.cuda.mem_get_info(device)
    result.update(device_free_bytes=int(free), device_total_bytes=int(total))
    status = Path("/proc/self/status").read_text().splitlines()
    for line in status:
        key, _, value = line.partition(":")
        if key in ("VmRSS", "VmHWM"):
            result[key.lower() + "_bytes"] = int(value.split()[0]) * 1024
    return result


def validate_status(handle, variant, expected_calls):
    state = handle.describe()
    if state.get("fallback_count") or state.get("last_error") or state.get("cleanup_error"):
        raise RuntimeError("Execution candidate reported fallback/error: " + repr(state))
    if state["effective"] != variant:
        raise RuntimeError("Requested execution variant is not effective: " + repr(state))
    if variant == "graph" and (state["capture_count"] != 1 or
                               state["replay_count"] != expected_calls or
                               state["input_update_count"] != expected_calls):
        raise RuntimeError("Graph did not replay/update exactly once for every call: " + repr(state))
    return state


def timed_call(backend, stable_input, torch, stream, start_event, end_event, clock_ns=time.perf_counter_ns):
    """One completed forward, with events on the common caller/default stream."""
    start_event.record(stream)
    start_ns = clock_ns()
    result = backend.forward(stable_input)
    returned_ns = clock_ns()
    end_event.record(stream)
    end_event.synchronize()
    complete_ns = clock_ns()
    values = {
        "execution_cuda_ms": float(start_event.elapsed_time(end_event)),
        "forward_call_wall_ms": (returned_ns - start_ns) / 1e6,
        "execution_complete_wall_ms": (complete_ns - start_ns) / 1e6,
    }
    if any(not math.isfinite(v) or v < 0 for v in values.values()):
        raise RuntimeError("Nonfinite/negative execution measurement: " + repr(values))
    if values["execution_cuda_ms"] == 0:
        raise RuntimeError("Zero CUDA-event execution duration cannot represent this E01 workload")
    return result, values


def measure(backend, stable_input, torch, stream, seconds, output, on_resource):
    events = [torch.cuda.Event(enable_timing=True) for _ in range(2)]
    measurements = {key: [] for key in FIELDS[2:]}
    final_output = None
    with (output / "frames.csv").open("x", newline="", buffering=1) as csv_stream:
        writer = csv.DictWriter(csv_stream, fieldnames=FIELDS)
        writer.writeheader()
        begin = time.monotonic()
        next_resource = begin + 5.0
        while time.monotonic() - begin < seconds:
            final_output, row = timed_call(backend, stable_input, torch, stream, *events)
            writer.writerow(dict(sample=len(measurements[FIELDS[2]]), elapsed_s=time.monotonic() - begin, **row))
            for key in measurements:
                measurements[key].append(row[key])
            now = time.monotonic()
            if now >= next_resource:
                on_resource("measurement_{:d}".format(len(measurements[FIELDS[2]])))
                next_resource = now + 5.0
        elapsed = time.monotonic() - begin
    return final_output, {key: summary(values) for key, values in measurements.items()}, elapsed


def run_worker(args, report):
    # Everything above this function is stdlib-only and can be CPU tested.
    import cv2
    import numpy as np
    import torch
    import tensorrt
    import ultralytics
    from soccer_perception.adapters.yolo import YoloBallDetector
    from soccer_perception.optimizations.graph import install

    frozen = frozen_case(args.run_dir)
    parameters = frozen["contract"]["parameters"]
    if not torch.cuda.is_available():
        raise RuntimeError("Robot CUDA runtime is required")
    engine = frozen["engine"]
    detector = YoloBallDetector(engine, parameters["det_conf"], 640, parameters["device"], [0], parameters["half"],
                               tensorrt=True, engine_path=engine, trt_batch=2)
    detector.load()
    original_predict = detector.model.predict

    def fixed_predict(*values, **kwargs):
        kwargs.update(imgsz=(640, 640), rect=False)
        return original_predict(*values, **kwargs)

    detector.model.predict = fixed_predict
    images = [cv2.imread(str(path)) for path in frozen["images"]]
    if any(image is None for image in images):
        raise ValueError("Could not decode frozen initialization pair")
    detector.detect_candidates_batch(images, top_k=parameters["yolo_top_k"])
    backend = detector.model.predictor.model
    if (not backend.engine or backend.dynamic or backend.fp16 or backend.nhwc or
            tuple(backend.bindings["images"].shape) != INPUT_SHAPE or len(backend.output_names) != 1 or
            tuple(backend.bindings[backend.output_names[0]].shape) != OUTPUT_SHAPE):
        raise ValueError("Actual backend differs from the frozen static FP32 E01 contract")
    if any(binding.data.dtype != torch.float32 for binding in backend.bindings.values()):
        raise ValueError("Actual TensorRT I/O is not FP32")
    with np.load(frozen["npz"], allow_pickle=False) as data:
        host_input, expected_raw = data["input"].copy(), data["raw"].copy()
    if (host_input.shape != INPUT_SHAPE or host_input.dtype != np.float32 or
            expected_raw.shape != OUTPUT_SHAPE or expected_raw.dtype != np.float32 or
            not np.isfinite(host_input).all() or not np.isfinite(expected_raw).all()):
        raise ValueError("Frozen Golden tensor shape/dtype/finite contract changed")
    report.update(
        engine_path=str(engine), engine_sha256=EXPECTED_ENGINE,
        provenance=frozen["provenance"], pair_key=frozen["pair_key"],
        input_sha256=hashlib.sha256(host_input.tobytes()).hexdigest(),
        input_shape=list(INPUT_SHAPE), output_shape=list(OUTPUT_SHAPE), external_dtype="float32",
        versions=dict(torch=torch.__version__, cuda=torch.version.cuda, tensorrt=tensorrt.__version__,
                      ultralytics=ultralytics.__version__, opencv=cv2.__version__),
        device=str(backend.device), device_name=torch.cuda.get_device_name(backend.device),
        baseline_initialization="One original full-detector call excluded before hook/warmup",
        resource_scope="Torch allocator plus device mem_get_info and process VmRSS/VmHWM; no empty_cache",
    )
    resource_stream = (args.output / "resources.jsonl").open("x", buffering=1)

    def snapshot(label):
        data = resources(torch, backend.device, label)
        resource_stream.write(json.dumps(data, allow_nan=False) + "\n")
        return data

    handle = None
    try:
        with torch.inference_mode(), torch.cuda.device(backend.device):
            # Both variants run on this same caller/default stream. Graph's
            # internal wait_stream edges put its entire forward inside events.
            caller = torch.cuda.default_stream(backend.device)
            with torch.cuda.stream(caller):
                stable_input = torch.from_numpy(host_input).to(backend.device)
                torch.cuda.synchronize(backend.device)
                report["resources_before_hook"] = snapshot("before_hook")
                handle = install(detector, args.variant)
                for index in range(args.warmup):
                    raw = backend.forward(stable_input)
                    if index == 0:
                        if not np.array_equal(raw.detach().cpu().numpy(), expected_raw):
                            raise RuntimeError("First excluded warmup output differs from current frozen Golden")
                        report["first_warmup_matches_golden"] = True
                torch.cuda.synchronize(backend.device)
                handle.synchronize()
                report["warmup_handle"] = validate_status(handle, args.variant, args.warmup)
                del raw
                report["resources_after_warmup"] = snapshot("after_warmup")
                raw, metrics, elapsed = measure(backend, stable_input, torch, caller, args.seconds, args.output, snapshot)
                count = metrics["execution_cuda_ms"]["samples"]
                handle.synchronize()
                report["before_restore"] = validate_status(handle, args.variant, args.warmup + count)
                if not np.array_equal(raw.detach().cpu().numpy(), expected_raw):
                    raise RuntimeError("Last measured output differs from current frozen Golden")
                report.update(metrics=metrics, samples=count, measured_loop_seconds=elapsed,
                              execution_batches_per_second=count / elapsed, final_output_matches_golden=True)
                report["resources_after_measurement"] = snapshot("after_measurement")
        if digest(engine) != EXPECTED_ENGINE:
            raise RuntimeError("Frozen Engine changed during measurement")
    finally:
        try:
            if handle is not None:
                report["before_restore"] = handle.describe()
                try:
                    handle.restore()
                    report["after_restore"] = handle.describe()
                    report["restore"] = "complete"
                except BaseException as error:
                    report["restore_error"] = repr(error)
                    raise
            report["resources_after_restore"] = snapshot("after_restore")
        finally:
            resource_stream.close()


def main(argv=None):
    parent = os.getppid()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=("b0", "graph"), required=True)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--seconds", type=float, default=60.0)
    args = parser.parse_args(argv)
    if args.warmup < 1 or not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error("warmup must be >=1 and seconds must be finite and positive")
    parent_exit_protection(parent)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    args.run_dir, args.output = output_directory(args.run_dir, args.output)
    report = dict(
        status="running", variant=args.variant, warmup=args.warmup, requested_seconds=args.seconds,
        formal_100_warmup_60_seconds=args.warmup == 100 and args.seconds == 60,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), pid=os.getpid(), parent_pid=parent,
        script_sha256=digest(Path(__file__)),
        scope="AutoBackend.forward only; stable frozen CUDA input; no preprocessing, NMS, camera or ROS",
        execution_cuda_scope="Caller-stream events around complete forward: Graph D2D input update, replay, output clone and stream waits included",
        forward_call_wall_scope="Only Python forward call; graph is asynchronous, so this is not completed inference latency",
        execution_complete_wall_scope="forward call plus end-event recording and end-event completion wait",
        comparison_warning="execution_cuda_ms is not the E03/stage0 execute_async_v2-only Engine event metric; compare b0 vs graph from THIS worker",
        coordinator_responsibility="No worker lock/power change: coordinator serializes GPU jobs, verifies source/power/clocks and schedules three interleaved rounds",
    )
    code = 0
    try:
        run_worker(args, report)
        report["status"] = "complete_pending_coordinator_review"
    except BaseException as error:
        report.update(status="failed_requires_review", error=repr(error))
        traceback.print_exc()
        code = 130 if isinstance(error, KeyboardInterrupt) else 1
    finally:
        report["completed_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        write_json(args.output / "result.json", report)
    print(json.dumps({key: report[key] for key in ("status", "variant")}, ensure_ascii=False), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
