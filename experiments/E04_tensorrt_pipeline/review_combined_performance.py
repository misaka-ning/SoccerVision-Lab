#!/usr/bin/env python3
"""CPU-only review of complete, bracketed E04 combination blocks.

Use the top-level E04 tool directory on PYTHONPATH. Recovered files and earlier
attempts are never modified. Partial blocks remain evidence, not comparisons.
"""
import argparse
import csv
import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

from performance_plan import matrix_scopes, schedule, stats, summarize
from run_performance_robot import validate_hooks, validate_packet_observation


ENGINE_SHA256 = "98c1b6bc703b29874d95db94d9cf51ef5b4a4142a7ca6cf22362a0c616fbf348"
VARIANTS = ("R0", "A2", "R4_AB", "R5_ABC")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def child(base, relative):
    value = Path(relative)
    require(not value.is_absolute() and ".." not in value.parts, "Unsafe artifact path: " + str(relative))
    path = (base / value).resolve()
    require(base.resolve() in path.parents, "Artifact escapes recovered directory: " + str(relative))
    return path


def verify_file(base, item):
    path = child(base, item["path"])
    require(path.is_file(), "Missing artifact: " + str(path))
    if "bytes" in item:
        require(path.stat().st_size == item["bytes"], "Artifact size differs: " + str(path))
    require(digest(path) == item["sha256"], "Artifact SHA256 differs: " + str(path))
    return path


def compare_nested(expected, actual, path="metrics"):
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and set(expected) == set(actual), path + ": keys differ")
        for key in expected:
            compare_nested(expected[key], actual[key], path + "." + key)
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(expected) == len(actual), path + ": list differs")
        for index, (a, b) in enumerate(zip(expected, actual)):
            compare_nested(a, b, path + "[%d]" % index)
    elif isinstance(expected, (float, int)) and not isinstance(expected, bool):
        require(type(actual) in (float, int) and math.isfinite(expected) and math.isfinite(actual)
                and abs(expected - actual) < 1e-9, path + ": numeric difference")
    else:
        require(type(expected) is type(actual) and expected == actual, path + ": value differs")


def rows_at(path):
    with path.open(encoding="utf-8", newline="") as stream:
        rows = [{k: float(v) for k, v in row.items()} for row in csv.DictReader(stream)]
    require(bool(rows), "No measurement rows")
    require(all(math.isfinite(v) for row in rows for v in row.values()), "Nonfinite CSV value")
    require(all(row["sample"] == index for index, row in enumerate(rows)), "CSV sample sequence differs")
    return rows


def timestamp(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def midpoint(job):
    return (timestamp(job["started_utc"]) + timestamp(job["completed_utc"])) / 2


def review_job(root, job, spec, payload):
    require(job["returncode"] == 0, "Complete job has nonzero return code")
    require(timestamp(job["completed_utc"]) - timestamp(job["started_utc"]) >= 60,
            "Job wall interval is shorter than the requested 60 seconds")
    artifacts = job.get("artifacts", [])
    require(bool(artifacts), "Complete job has no frozen artifacts")
    paths = {str(verify_file(root, item).relative_to(root.resolve())) for item in artifacts}
    output = child(root, Path(job["output"]).name)
    required = [output / "frames.csv", output / "result.json", root / (output.name + "_hooks.json")]
    required.append(output / ("effective_runtime.json" if spec["scope"] == "detector" else "progress.json"))
    if spec["scope"] == "system":
        required.append(output / "deployment_config.json")
    require(all(str(p.relative_to(root)) in paths for p in required), "Required measurement file is not hash-bound")
    rows = rows_at(output / "frames.csv")
    require(len(rows) == job["samples"], "CSV sample count differs")
    metrics = summarize(output / "frames.csv", spec["scope"])
    compare_nested(metrics, job["metrics"])
    result = read(output / "result.json")
    require(result["status"] == "complete", "Worker result is incomplete")
    hook = validate_hooks(root / (output.name + "_hooks.json"), spec, len(rows), payload["expected_runtime"])
    components = hook["detectors"][0]["before_restore"]["components"]
    warm = hook["warmup_checkpoint"][0]["components"]
    require(all(v.get("last_error") is None for state in (components, warm) for v in state.values()),
            "Candidate records an earlier hook error")
    if spec["switches"].get("engine") == "graph":
        for key in ("calls", "replay_count", "input_update_count", "output_clone_count"):
            require(warm["engine"][key] == 100 and components["engine"][key] == 100 + len(rows),
                    "Graph warmup/measurement/clone counters differ: " + key)
        require(not components["engine"].get("disabled_reason") and not components["engine"].get("cleanup_error"),
                "Graph records disable/cleanup failure")
    if spec["switches"].get("preprocess") == "c2":
        require(warm["preprocess"]["calls"] == warm["preprocess"]["success_count"] == 100,
                "C2 warmup counter differs")
    if spec["scope"] == "detector":
        runtime = read(output / "effective_runtime.json")
        require(runtime["engine_sha256"] == ENGINE_SHA256 and runtime["warmup_excluded"] == 100,
                "Replay Engine/warmup differs")
        require(runtime["top_k"] == 5, "Replay top_k differs")
        require(result["seconds"] == 60 and result["samples"] == len(rows), "Replay duration/count differs")
        require(all(r["left_candidates"] == r["right_candidates"] == 1 for r in rows),
                "Frozen detector pair must have one candidate per eye")
    else:
        progress = read(output / "progress.json")
        require(progress["warmup_total"] == 100 and progress["elapsed"] >= 60
                and progress["completed"] == len(rows), "System warmup/duration/count differs")
        deployment = read(output / "deployment_config.json")
        parameters = deployment["parameters"]
        require(parameters["yolo_top_k"] == 5 and parameters["yolo_trt_batch"] == 2
                and parameters["imgsz"] == 640 and parameters["det_conf"] == .45
                and str(deployment["ros_domain_id"]) == "87", "System shape/threshold/top_k/ROS domain differs")
        require(payload.get("packet_observation") is True, "Combined system requires packet observation")
        validate_packet_observation(hook, metrics, len(rows))
        for row in rows:
            require(row["frame_idx"].is_integer() and row["frames_since_measurement"].is_integer()
                    and row["frames_since_measurement"] >= 0, "Invalid packet frame/age integer")
    if spec["switches"].get("postprocess") == "a2":
        end, begin = components["postprocess"], warm["postprocess"]
        require(begin["predict_calls"] == 100, "A2 warmup predict count differs")
        delta = {key: end[key] - begin[key] for key in
                 ("packed_batches", "packed_rows", "d2h_calls", "d2h_bytes", "pack_wall_ms_total")}
        require(delta["d2h_calls"] == delta["packed_batches"] and delta["d2h_bytes"] == 24 * delta["packed_rows"],
                "A2 D2H rows/bytes differ")
        nonempty = sum(r["left_candidates"] + r["right_candidates"] > 0 for r in rows)
        require(delta["packed_batches"] == nonempty, "A2 nonempty batch count differs")
        if spec["scope"] == "detector":
            require(delta["packed_batches"] == len(rows) and delta["packed_rows"] == 2 * len(rows)
                    and delta["d2h_bytes"] == 48 * len(rows), "A2 fixed-pair transfer differs")
        # A2 transfers all NMS survivors before top_k; system candidate counts
        # after top_k are not a general equality constraint on packed_rows.
        require(abs(sum(r["a2_pack_method_ms"] for r in rows) - delta["pack_wall_ms_total"]) < 1e-7,
                "Per-frame A2 pack wall differs from warm/final cumulative delta")
    return dict(name=spec["name"], scope=spec["scope"], round=spec["round"], position=spec["position"],
                variant=spec["variant"], attempt=job["attempt"], samples=len(rows), metrics=metrics,
                midpoint=midpoint(job), artifact_count=len(artifacts)), rows


def latency_changes(base, candidate):
    return {key: {q: dict(baseline=base[key][q], candidate=candidate[key][q],
                         saved_ms=base[key][q] - candidate[key][q],
                         reduction_percent=(base[key][q] - candidate[key][q]) / base[key][q] * 100)
                  for q in ("mean", "p95", "p99")}
            for key in candidate if key.endswith("_ms") and key in base and base[key]["mean"] > 0}


def pooled(rows_by_run, scope):
    rows = [row for run in rows_by_run for row in run]
    result = {key: stats([r[key] for r in rows]) for key in rows[0] if key.endswith("_ms")}
    if scope == "system":
        seconds = sum(r[-1]["cycle_end"] - r[0]["cycle_start"] for r in rows_by_run)
        pub_seconds = sum(r[-1]["publish_end"] - r[0]["publish_end"] for r in rows_by_run)
        result.update(processing_hz=len(rows) / seconds,
                      publish_hz=sum(len(r) - 1 for r in rows_by_run) / pub_seconds,
                      hz_sample_seconds=seconds, publish_sample_seconds=pub_seconds)
        flags = ("measurement_valid", "tracking_valid", "track_initialized", "coasting")
        result["packet_flags"] = {key: dict(count=sum(r[key] for r in rows),
                                           fraction=sum(r[key] for r in rows) / len(rows)) for key in flags}
        result["candidate_counts"] = {eye: stats([r[eye + "_candidates"] for r in rows]) for eye in ("left", "right")}
        result["candidate_coverage"] = dict(both_nonempty=sum(r["left_candidates"] > 0 and r["right_candidates"] > 0 for r in rows),
                                            neither=sum(r["left_candidates"] == r["right_candidates"] == 0 for r in rows), samples=len(rows))
    return result


def paired_block(ordered):
    before, after = ordered[0], ordered[-1]
    base = {key: {q: (before["metrics"][key][q] + after["metrics"][key][q]) / 2
                  for q in ("mean", "p95", "p99")} for key in before["metrics"] if key.endswith("_ms")}
    changes = []
    for candidate in ordered[1:-1]:
        item = dict(variant=candidate["variant"], latency=latency_changes(base, candidate["metrics"]))
        weight = ((candidate["midpoint"] - before["midpoint"]) /
                  (after["midpoint"] - before["midpoint"]))
        item["time_interpolation_weight"] = weight
        primary = "detector_wall_ms" if candidate["scope"] == "detector" else "read_ready_to_publish_ms"
        a, b = before["metrics"][primary]["mean"], after["metrics"][primary]["mean"]
        interpolated = a + (b - a) * weight
        item["interpolated_primary_reduction_percent"] = (
            interpolated - candidate["metrics"][primary]["mean"]) / interpolated * 100
        if candidate["scope"] == "system":
            item["hz"] = {key: dict(baseline=(before["metrics"][key] + after["metrics"][key]) / 2,
                                      candidate=candidate["metrics"][key],
                                      gain_percent=(candidate["metrics"][key] /
                                                    ((before["metrics"][key] + after["metrics"][key]) / 2) - 1) * 100)
                          for key in ("processing_hz", "publish_hz")}
        changes.append(item)
    by_variant = {j["variant"]: j for j in ordered[1:-1]}
    increments = []
    for old, new in (("A2", "R4_AB"), ("R4_AB", "R5_ABC")):
        a, b = by_variant[old]["metrics"], by_variant[new]["metrics"]
        item = dict(reference=old, candidate=new, latency=latency_changes(a, b))
        if before["scope"] == "system":
            item["hz_gain_percent"] = {key: (b[key] / a[key] - 1) * 100
                                       for key in ("processing_hz", "publish_hz")}
        increments.append(item)
    return dict(scope=before["scope"], round=before["round"], paired=changes, increments=increments,
                interpolation_note="Job midpoint approximation including initialization; sensitivity only")


def macro_comparisons(blocks):
    """Equal block weights; never treat raw frames as independent repeats."""
    result = {}
    for scope in ("detector", "system"):
        selected = [b for b in blocks if b["scope"] == scope]
        if not selected:
            continue
        comparisons = {}
        for label, old, new in (("A2_vs_R0", "R0", "A2"), ("R4_vs_R0", "R0", "R4_AB"),
                                ("R5_vs_R0", "R0", "R5_ABC"), ("R4_vs_A2", "A2", "R4_AB"),
                                ("R5_vs_R4", "R4_AB", "R5_ABC")):
            records = []
            for block in selected:
                source = block["paired"] if old == "R0" else block["increments"]
                records.append(next(r for r in source if r.get("variant", r.get("candidate")) == new))
            common = set.intersection(*(set(r["latency"]) for r in records))
            item = dict(independent_blocks=len(records), reference=old, candidate=new,
                        latency={key: {q: {field: statistics.mean(r["latency"][key][q][field] for r in records)
                                           for field in ("saved_ms", "reduction_percent")}
                                       for q in ("mean", "p95", "p99")} for key in sorted(common)})
            if scope == "system":
                item["hz_gain_percent"] = {key: statistics.mean(
                    r["hz"][key]["gain_percent"] if old == "R0" else r["hz_gain_percent"][key] for r in records)
                    for key in ("processing_hz", "publish_hz")}
            comparisons[label] = item
        result[scope] = comparisons
    return result


def review(root, integrity_label="interrupted_recovery_v1"):
    root = Path(root).resolve()
    require(re.fullmatch(r"[A-Za-z0-9_-]+", integrity_label) is not None, "Invalid integrity label")
    payload = read(root / "performance_manifest.json")
    require(payload.get("matrix") == "combined_pipeline", "Only the frozen combined_pipeline matrix is supported")
    specs = schedule(matrix_scopes("combined_pipeline"), "combined_pipeline")
    fingerprint = digest(root / "performance_manifest.json")
    frozen_schedule = hashlib.sha256(json.dumps(specs, sort_keys=True).encode()).hexdigest()
    require(payload.get("schedule_sha256") == frozen_schedule, "Frozen schedule SHA256 differs")
    require(payload["engine_info"]["sha256"] == ENGINE_SHA256, "Frozen E01 Engine identity differs")
    integrity = read(root / (integrity_label + "_integrity.json"))
    require(integrity.get("errors") == [], "Recovery integrity has errors or no explicit error list")
    identity_keys = [key for key in ("performance_manifest_sha256", "phase_manifest_sha256", "manifest_sha256") if key in integrity]
    require(bool(identity_keys) and all(integrity[k] == fingerprint for k in identity_keys), "Recovery manifest identity differs")
    recovery = read(root / (integrity_label + "_manifest.json"))
    for item in recovery["files"]:
        verify_file(root, item)
    for item in payload.get("files", []):
        local = root if child(root, item["path"]).is_file() else root.parent
        verify_file(local, item)
    jobs = read(root / "performance_jobs.json")
    by_spec = {s["name"]: s for s in specs}
    errors, reviewed, rows_by_name, complete, seen, invalid = [], [], {}, {}, set(), set()
    for job in jobs:
        name = job.get("name", "<missing>")
        try:
            require(name in by_spec, "Unknown schedule job")
            spec = by_spec[name]
            require(json.dumps({k: job.get(k) for k in spec}, sort_keys=True) == json.dumps(spec, sort_keys=True),
                    "Job fields differ from frozen schedule")
            require(job["payload_sha256"] == fingerprint, "Job belongs to a different payload")
            require(type(job["attempt"]) is int and job["attempt"] >= 1, "Invalid attempt index")
            identity = (name, job["attempt"])
            require(identity not in seen, "Duplicate job/attempt identity")
            seen.add(identity)
            if job["status"] != "complete":
                for item in job.get("artifacts", []):
                    verify_file(root, item)
                continue
            require(name not in complete, "Multiple complete attempts for the same schedule job")
            complete[name] = job
            record, rows = review_job(root, job, spec, payload)
            reviewed.append(record)
            rows_by_name[name] = rows
        except Exception as error:
            errors.append(dict(job=name, attempt=job.get("attempt"), error=str(error)))
            invalid.add(name)
    valid = {j["name"]: j for j in reviewed if j["name"] not in invalid}
    blocks, paired, eligible_names = [], [], set()
    for scope in matrix_scopes("combined_pipeline"):
        for round_index in (1, 2, 3):
            group = [s for s in specs if s["scope"] == scope and s["round"] == round_index]
            names = [s["name"] for s in group]
            missing = [name for name in names if name not in valid]
            block = dict(scope=scope, round=round_index, eligible=False, missing_or_invalid_names=missing,
                         valid_complete_names=[name for name in names if name in valid])
            if not missing:
                ordered = [valid[name] for name in names]
                key = "detector_wall_ms" if scope == "detector" else "read_ready_to_publish_ms"
                drift = abs(ordered[-1]["metrics"][key]["mean"] / ordered[0]["metrics"][key]["mean"] - 1) * 100
                block["baseline_drift_percent"] = drift
                if drift > payload.get("plan", {}).get("max_bracket_drift_percent", 3):
                    errors.append(dict(block=[scope, round_index], error="R0 bracket drift exceeds frozen limit"))
                elif not all(b["midpoint"] > a["midpoint"] for a, b in zip(ordered, ordered[1:])):
                    errors.append(dict(block=[scope, round_index], error="Block timestamp order differs; do not mix stale and retried jobs"))
                else:
                    block["eligible"] = True
                    eligible_names.update(names)
                    paired.append(paired_block(ordered))
            blocks.append(block)
    pools = {}
    for scope in matrix_scopes("combined_pipeline"):
        pools[scope] = {}
        for variant in VARIANTS:
            selected = [j for j in reviewed if j["name"] in eligible_names and j["scope"] == scope and j["variant"] == variant]
            if selected:
                pools[scope][variant] = dict(jobs=len(selected), rounds=sorted({j["round"] for j in selected}),
                    samples=sum(j["samples"] for j in selected),
                    metrics=pooled([rows_by_name[j["name"]] for j in selected], scope))
    all_complete = all(b["eligible"] for b in blocks) and not errors
    return dict(status="collection_review" if all_complete else "partial_collection_review",
                validation_passed=not errors, errors=errors, matrix="combined_pipeline",
                full_matrix_reviewed=all_complete,
                review_sources=dict(script_sha256=digest(Path(__file__)),
                    performance_plan_sha256=digest(Path(schedule.__code__.co_filename)),
                    validators_sha256=digest(Path(validate_hooks.__code__.co_filename))),
                performance_manifest_sha256=fingerprint, schedule_sha256=frozen_schedule,
                recovered_attempts=len(jobs), complete_attempts=sum(j["status"] == "complete" for j in jobs),
                historical_attempts=[{k: j.get(k) for k in ("name", "attempt", "status", "reason", "error")} for j in jobs if j["status"] != "complete"],
                job_reviews=reviewed, blocks=blocks, verified_blocks=[b for b in blocks if b["eligible"]],
                incomplete_blocks=[b for b in blocks if not b["eligible"]],
                complete_jobs_excluded_from_pairing=[j["name"] for j in reviewed if j["name"] not in eligible_names],
                pools=pools, block_comparisons=paired, paired_macro=macro_comparisons(paired),
                production_adopted=False, stability_approved=False,
                statistics_note="Pools use only five-job valid blocks; quantiles pool raw frames. Paired units are blocks, not frames. Incomplete blocks and historical attempts are retained but excluded.",
                pack_note="A2 pack method wall is already included in predict/detector/system wall; never add it again.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovered", type=Path, required=True)
    parser.add_argument("--integrity-label", default="interrupted_recovery_v1")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    value = review(args.recovered, args.integrity_label)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    print(json.dumps({k: value[k] for k in ("status", "validation_passed", "errors", "recovered_attempts", "complete_attempts", "verified_blocks", "incomplete_blocks")}, ensure_ascii=False, indent=2))
    return 0 if value["validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
