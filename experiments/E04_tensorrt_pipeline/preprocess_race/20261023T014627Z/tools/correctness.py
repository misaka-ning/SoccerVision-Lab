"""Exact replay checks for preprocessing candidates, never a timing harness.

Only caller-provided Val images are read. CPU copies deliberately synchronize
tensor data here; never install these capture hooks during performance runs.
The R0 tensor reference stays in RAM and is not exported as hundreds of NPZs.
"""

from __future__ import annotations

import hashlib
import json
import math
import traceback
from pathlib import Path

import numpy as np


_MISSING = object()


def _json_value(value):
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(v) for v in value]
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite_float": str(value)}
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError("Unsupported semantic value: " + type(value).__name__)


def _array(value):
    if isinstance(value, np.ndarray):
        return np.array(value, copy=True, order="C")
    # Avoid importing GPU libraries merely by importing this CPU helper.
    if callable(getattr(value, "detach", None)):
        return np.array(value.detach().cpu().numpy(), copy=True, order="C")
    raise TypeError("Expected a tensor or ndarray, got " + type(value).__name__)


def _snapshot(value):
    if isinstance(value, np.ndarray) or callable(getattr(value, "detach", None)):
        return {"kind": "array", "data": _array(value)}
    if isinstance(value, (list, tuple)):
        return {"kind": type(value).__name__, "items": [_snapshot(x) for x in value]}
    if isinstance(value, dict):
        return {"kind": "dict", "items": {str(k): _snapshot(v) for k, v in value.items()}}
    return {"kind": "scalar", "value": _json_value(value)}


def _array_info(array):
    return {"shape": list(array.shape), "dtype": str(array.dtype),
            "sha256": hashlib.sha256(array.tobytes(order="C")).hexdigest()}


def _tree_info(tree):
    if tree["kind"] == "array":
        return dict(kind="array", **_array_info(tree["data"]))
    if tree["kind"] in ("list", "tuple"):
        return {"kind": tree["kind"], "items": [_tree_info(x) for x in tree["items"]]}
    if tree["kind"] == "dict":
        return {"kind": "dict", "items": {k: _tree_info(v) for k, v in tree["items"].items()}}
    return dict(tree)


def _arrays(tree):
    if tree["kind"] == "array":
        yield tree["data"]
    elif tree["kind"] in ("tuple", "list"):
        for item in tree["items"]:
            yield from _arrays(item)
    elif tree["kind"] == "dict":
        for item in tree["items"].values():
            yield from _arrays(item)


def _differences(expected, actual, path="", limit=20):
    """Compare exact structure and array bytes; report paths, never big arrays."""
    errors = []

    def compare(a, b, where):
        if len(errors) >= limit:
            return
        if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
            if not isinstance(a, np.ndarray) or not isinstance(b, np.ndarray):
                errors.append(where + ": array type differs")
            elif a.shape != b.shape or a.dtype != b.dtype:
                errors.append(where + ": array shape/dtype differs")
            elif a.tobytes(order="C") != b.tobytes(order="C"):
                errors.append(where + ": array bytes differ")
        elif type(a) is not type(b):
            errors.append(where + ": type differs")
        elif isinstance(a, dict):
            if a.keys() != b.keys():
                errors.append(where + ": keys differ")
            else:
                for key in a:
                    compare(a[key], b[key], where + "/" + str(key))
        elif isinstance(a, (list, tuple)):
            if len(a) != len(b):
                errors.append(where + ": length differs")
            else:
                for index, (x, y) in enumerate(zip(a, b)):
                    compare(x, y, where + "/" + str(index))
        elif a != b:
            errors.append(where + ": value differs")

    compare(expected, actual, path)
    return errors


class _Patches:
    def __init__(self):
        self.items = []

    def set(self, obj, name, replacement):
        self.items.append((obj, name, vars(obj).get(name, _MISSING), replacement))
        setattr(obj, name, replacement)

    def restore(self):
        # Preflight all owners before making a partial restoration.
        for obj, name, old, replacement in self.items:
            if vars(obj).get(name, _MISSING) is not replacement:
                raise RuntimeError("Capture ownership changed: " + name)
        for obj, name, old, replacement in reversed(self.items):
            if old is _MISSING:
                delattr(obj, name)
            else:
                setattr(obj, name, old)
        self.items = []


class _Capture:
    def __init__(self, detector):
        self.current = None
        self.patches = _Patches()
        predictor = detector.model.predictor
        old_preprocess = predictor.preprocess
        old_inference = predictor.inference
        old_convert = detector._result_to_candidates

        def preprocess(*args, **kwargs):
            result = old_preprocess(*args, **kwargs)
            self.current["input"].append(_array(result))
            return result

        def inference(*args, **kwargs):
            result = old_inference(*args, **kwargs)
            # Capture BEFORE postprocess/NMS can modify an output in place.
            self.current["raw"].append(_snapshot(result))
            return result

        def convert(result, *args, **kwargs):
            boxes = getattr(result, "boxes", _MISSING)
            if boxes is _MISSING:
                raise TypeError("Expected ordinary Results, not a legacy fast result")
            final = None if boxes is None else _array(boxes.data)
            candidates = old_convert(result, *args, **kwargs)
            self.current["final_boxes"].append(final)
            self.current["candidates"].append(_json_value([x.to_dict() for x in candidates]))
            return candidates

        try:
            self.patches.set(predictor, "preprocess", preprocess)
            self.patches.set(predictor, "inference", inference)
            self.patches.set(detector, "_result_to_candidates", convert)
        except Exception:
            self.patches.restore()
            raise

    def start(self):
        self.current = {"input": [], "raw": [], "final_boxes": [], "candidates": []}

    def finish(self):
        result = self.current
        if len(result["input"]) != 1 or len(result["raw"]) != 1:
            raise ValueError("Each stereo pair must call preprocess/inference exactly once")
        if len(result["final_boxes"]) != 2 or len(result["candidates"]) != 2:
            raise ValueError("Each stereo pair must yield exactly left/right Results")
        image = result["input"][0]
        if image.shape != (2, 3, 640, 640) or image.dtype != np.float32 or not np.isfinite(image).all():
            raise ValueError("Input is not finite FP32 [2,3,640,640]")
        raw_arrays = list(_arrays(result["raw"][0]))
        if not any(x.shape == (2, 5, 8400) and x.dtype == np.float32 for x in raw_arrays):
            raise ValueError("No frozen FP32 [2,5,8400] raw TensorRT output captured")
        if any(not np.isfinite(x).all() for x in raw_arrays):
            raise ValueError("Nonfinite raw inference output")
        for boxes in result["final_boxes"]:
            if boxes is not None and (boxes.ndim != 2 or boxes.shape[1] != 6 or
                                      boxes.dtype != np.float32 or not np.isfinite(boxes).all()):
                raise ValueError("Expected finite FP32 final Nx6 boxes")
        return result

    def restore(self):
        self.patches.restore()


class _ReplaySource:
    def __init__(self, pairs, images, calibration):
        self.pairs, self.images, self.calibration = pairs, images, calibration
        self.index = 0
        self.current = None

    def open(self):
        from soccer_perception.types import CameraIntrinsics
        return CameraIntrinsics(np.asarray(self.calibration["K"], np.float64),
                                float(self.calibration["baseline_m"]), float(self.calibration["fps"]),
                                tuple(self.calibration["image_size"]))

    def read(self):
        from soccer_perception.types import StereoFrame
        if self.index >= len(self.pairs):
            return None
        index = self.index
        pair = self.pairs[index]
        # Never expose the caller's original images to a potentially bad hook.
        left = self.images[pair["left"]].copy()
        right = self.images[pair["right"]].copy()
        self.current = (pair, left, right)
        self.index += 1
        return StereoFrame(1000.0 + index / 30.0, left, right, index)

    def assert_unchanged(self):
        pair, left, right = self.current
        for key, value in (("left", left), ("right", right)):
            reference = self.images[pair[key]]
            if value.dtype != reference.dtype or value.shape != reference.shape or not np.array_equal(value, reference):
                raise ValueError("Candidate mutated its source image: " + pair[key])

    def close(self):
        pass


class _NullVisualizer:
    def open(self):
        pass

    def close(self):
        pass

    def update(self, *args):
        pass


def _semantic(packet):
    from soccer_perception.ros.output import (build_ball_position_camera_payload,
                                               build_ball_camera_diagnostics)
    diagnostics = build_ball_camera_diagnostics(packet)
    diagnostics.pop("fps", None)
    diagnostics.pop("det_ms", None)
    return _json_value({
        "frame_idx": packet.frame_idx, "timestamp": packet.timestamp, "status": packet.status,
        "selected": [x.to_dict() if x is not None else None for x in (packet.left_det, packet.right_det)],
        "candidate_diagnostics": packet.candidate_diagnostics,
        "measurement": packet.ball_3d_measurement.to_dict(),
        "track": packet.camera_track_state.to_dict(),
        "ros_payload": build_ball_position_camera_payload(packet),
        "diagnostics": diagnostics,
    })


def _active_status(detector):
    status = detector.optimization_status()
    if status["mode"] != "a2_graph" or not status["enabled"]:
        raise ValueError("R0 must be the existing enabled a2_graph detector")
    components = status["state"]["components"]
    for name in ("postprocess", "engine", "preprocess"):
        component = components[name]
        if component.get("fallback_count", 0) or component.get("last_error") or component.get("cleanup_error"):
            raise ValueError("Existing optimization did not remain clean: " + name)
    if components["postprocess"]["effective"] != "a2" or components["engine"]["effective"] != "graph":
        raise ValueError("A2/Graph requested but not actually effective")
    if components["engine"]["capture_count"] != 1:
        raise ValueError("Expected exactly one existing Graph capture")
    return _json_value(status)


def _check_counter_deltas(before, after, count):
    b, a = before["state"]["components"], after["state"]["components"]
    for key in ("calls", "replay_count", "input_update_count", "output_clone_count"):
        if a["engine"][key] - b["engine"][key] != count:
            raise ValueError("Graph counter delta differs from pair count: " + key)
    if a["postprocess"]["predict_calls"] - b["postprocess"]["predict_calls"] != count:
        raise ValueError("A2 predict counter delta differs from pair count")


def _input_difference(expected, actual):
    result = {"shape_equal": expected.shape == actual.shape,
              "dtype_equal": expected.dtype == actual.dtype, "exact": False,
              "max_abs": None, "mean_abs": None, "different_elements": None}
    if not result["shape_equal"] or not result["dtype_equal"]:
        return result
    exact = expected.tobytes(order="C") == actual.tobytes(order="C")
    if exact:
        result.update(exact=True, max_abs=0.0, mean_abs=0.0, different_elements=0)
    else:
        delta = np.subtract(expected, actual, dtype=np.float64)
        np.abs(delta, out=delta)
        result.update(max_abs=float(delta.max()), mean_abs=float(delta.mean()),
                      different_elements=int(np.count_nonzero(expected.view(np.uint32) != actual.view(np.uint32))))
    return result


def _pair_summary(variant, pair, index, captured, errors, reference=None):
    semantic = captured["semantic"]
    expected = captured if reference is None else reference
    exact = {name + "_exact": not _differences(expected[name], captured[name], name)
             for name in ("raw", "final_boxes", "candidates", "semantic")}
    return dict(exact, **{"variant": variant, "pair_key": pair["pair_key"], "frame_idx": index,
            "replay_timestamp": 1000.0 + index / 30.0, "passed": not errors,
            "errors": errors, "input": _array_info(captured["input"][0]),
            "input_diff": _input_difference(expected["input"][0], captured["input"][0]),
            "raw": _tree_info(captured["raw"][0]),
            "final_boxes": [None if x is None else _array_info(x) for x in captured["final_boxes"]],
            "candidate_counts": [len(x) for x in captured["candidates"]],
            "measurement_valid": semantic["measurement"]["valid"],
            "tracking_valid": semantic["ros_payload"]["valid"]})


def _run_variant(detector, config, pairs, images, calibration, installer, variant, references):
    from soccer_perception.pipeline import SoccerPerceptionPipeline
    from soccer_perception.core.tracking import AlphaBetaBallTracker
    entry = {"variant": variant, "passed": False, "excluded": True, "errors": [],
             "completed_pairs": 0, "restore": {}}
    rows, collected = [], []
    pipeline = capture = candidate = load_patch = None
    try:
        detector.load()
        entry["start_status"] = _active_status(detector)
        if variant != "R0":
            candidate = installer(detector.model.predictor, variant)
        capture = _Capture(detector)
        source = _ReplaySource(pairs, images, calibration)
        tracker = AlphaBetaBallTracker(max_coast_frames=config.max_coast_frames,
                                      max_coast_time_s=config.max_coast_time_s,
                                      velocity_decay=config.velocity_decay)
        pipeline = SoccerPerceptionPipeline(source, detector, tracker, config,
                                             visualizer=_NullVisualizer())
        load_patch = _Patches()
        load_patch.set(detector, "load", lambda: None)
        pipeline.open()
        for index, pair in enumerate(pairs):
            capture.start()
            packet = pipeline.next_packet()
            if packet is None:
                raise ValueError("Replay ended before all Val pairs")
            source.assert_unchanged()
            actual = capture.finish()
            actual["semantic"] = _semantic(packet)
            errors = []
            if references is None:
                collected.append(actual)
            else:
                for name in ("input", "raw", "final_boxes", "candidates", "semantic"):
                    errors.extend(_differences(references[index][name], actual[name], name))
            rows.append(_pair_summary(variant, pair, index, actual, errors,
                                      None if references is None else references[index]))
            entry["completed_pairs"] += 1
            if errors:
                entry["errors"].append({"pair_key": pair["pair_key"], "differences": errors})
        entry["final_status"] = _active_status(detector)
        _check_counter_deltas(entry["start_status"], entry["final_status"], len(pairs))
        if candidate is not None:
            status = _json_value(candidate.describe())
            entry["candidate_status"] = status
            if (status["calls"] != len(pairs) or status["success_count"] != len(pairs) or
                    status["fallback_count"] or status["last_error"] or status["effective"] != variant):
                raise ValueError("Candidate did not execute cleanly on every pair")
    except Exception as error:
        entry["errors"].append({"exception": type(error).__name__, "message": str(error),
                                "traceback": traceback.format_exc()})
    finally:
        # Ownership-sensitive outer hooks MUST be removed before either inner
        # candidate or A2/Graph restoration. Never overwrite an unknown owner.
        safe_to_close = True
        for name, handle in (("capture", capture), ("candidate", candidate), ("load", load_patch)):
            if handle is None:
                entry["restore"][name] = "not_installed"
                continue
            if not safe_to_close and name != "load":
                entry["restore"][name] = "blocked_by_outer_restore_failure"
                continue
            try:
                handle.restore()
                entry["restore"][name] = "passed"
                if name == "candidate":
                    entry["candidate_after_restore"] = _json_value(candidate.describe())
            except Exception as error:
                safe_to_close = False
                entry["restore"][name] = "failed: " + repr(error)
                entry["errors"].append({"cleanup": name, "exception": type(error).__name__,
                                        "message": str(error), "traceback": traceback.format_exc()})
        if safe_to_close:
            try:
                if pipeline is not None:
                    pipeline.close()
                else:
                    detector.close()
                entry["restore"]["pipeline_detector"] = "passed"
            except Exception as error:
                entry["restore"]["pipeline_detector"] = "failed: " + repr(error)
                entry["errors"].append({"cleanup": "pipeline_detector", "exception": type(error).__name__,
                                        "message": str(error), "traceback": traceback.format_exc()})
        else:
            entry["restore"]["pipeline_detector"] = "blocked_by_outer_restore_failure"
        entry["restore_passed"] = all(v in ("passed", "not_installed") for v in entry["restore"].values())
    entry["passed"] = not entry["errors"] and entry["completed_pairs"] == len(pairs) and entry["restore_passed"]
    entry["excluded"] = not entry["passed"]
    return entry, rows, collected


def run_correctness(detector, config, cases_doc, images_by_name, calibration_dict,
                    install_candidate, output_dir):
    """Replay R0/canvas/reuse against a fresh model and fresh tracker each time.

    The caller supplies a configured, currently unloaded detector, BackendConfig,
    cases.json dictionary, name->BGR ndarray mapping, frozen calibration and
    candidate install(predictor, variant). No camera/ROS/CLI is invoked here.
    Returns a JSON-compatible report; exceptions from candidates are retained
    with traceback and mark that candidate excluded. Files never overwrite an
    earlier collection. Tensor exactness is bitwise (shape/dtype/bytes).
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if any((out / name).exists() for name in ("correctness.json", "per_pair.json")):
        raise FileExistsError("Correctness output already exists: " + str(out))
    report = {"passed": False, "split": cases_doc.get("split"), "test_accessed": False,
              "reference": "fresh R0: current configured E01 + A2 + Graph",
              "comparisons": "exact input/raw/final boxes/candidate order/left-right/downstream semantics",
              "not_performance_data": True, "camera_opened": False, "ros_published": False,
              "timestamp_rule": "1000 + index/30; frame_idx=index",
              "excluded_volatile_semantics": ["diagnostics.fps", "diagnostics.det_ms"],
              "variants": [], "eligible_candidates": [], "errors": []}
    rows = []
    try:
        if cases_doc.get("split") != "val" or cases_doc.get("test_accessed") is not False:
            raise ValueError("Only explicitly declared non-Test Val cases are permitted")
        pairs = cases_doc["pairs"]
        if not isinstance(pairs, list) or not pairs:
            raise ValueError("cases_doc.pairs must be a nonempty list")
        seen = set()
        for pair in pairs:
            if pair["pair_key"] in seen:
                raise ValueError("Duplicate pair_key")
            seen.add(pair["pair_key"])
            for key in ("left", "right"):
                value = images_by_name[pair[key]]
                if not isinstance(value, np.ndarray) or value.dtype != np.uint8 or value.ndim != 3 or value.shape[2] != 3:
                    raise ValueError("Images must be uint8 BGR HWC: " + pair[key])
                if value.shape[:2] != tuple(calibration_dict["image_size"])[::-1]:
                    raise ValueError("Image shape differs from frozen calibration")
        if getattr(detector, "model", None) is not None:
            raise ValueError("Pass an unloaded detector; each variant must own one fresh load")
        report["pair_count"] = len(pairs)
        report["calibration"] = _json_value(calibration_dict)
        references = None
        blocked = None
        for variant in ("R0", "canvas", "reuse"):
            if blocked:
                report["variants"].append({"variant": variant, "passed": False, "excluded": True,
                                           "skipped": blocked})
                continue
            entry, pair_rows, collected = _run_variant(detector, config, pairs, images_by_name,
                                                       calibration_dict, install_candidate, variant, references)
            report["variants"].append(entry)
            rows.extend(pair_rows)
            if variant == "R0":
                if not entry["passed"]:
                    blocked = "R0 reference failed"
                else:
                    references = collected
            if not entry["restore_passed"]:
                blocked = "Previous variant could not safely restore; explicit cleanup required"
        report["passed"] = all(x["passed"] for x in report["variants"])
        report["eligible_candidates"] = [x["variant"] for x in report["variants"]
                                          if x["variant"] != "R0" and x["passed"]]
    except Exception as error:
        report["errors"].append({"exception": type(error).__name__, "message": str(error),
                                 "traceback": traceback.format_exc()})
    for variant in ("R0", "canvas", "reuse"):
        report[variant] = next((x for x in report["variants"] if x["variant"] == variant),
                               {"variant": variant, "passed": False, "excluded": True, "skipped": "input validation failed"})
    for name, value in (("correctness.json", report), ("per_pair.json", rows)):
        with (out / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
    if not report["R0"]["passed"]:
        raise RuntimeError("R0 correctness reference failed; see " + str(out / "correctness.json"))
    if any(not entry.get("restore_passed", True) for entry in report["variants"]):
        raise RuntimeError("Unsafe candidate cleanup; see " + str(out / "correctness.json"))
    return report
