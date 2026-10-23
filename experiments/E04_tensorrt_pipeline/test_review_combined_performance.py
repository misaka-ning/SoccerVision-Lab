"""Synthetic CPU evidence fixtures; no hardware or benchmark execution."""
import copy
import csv
import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from performance_plan import schedule, summarize
from review_combined_performance import ENGINE_SHA256, review


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def artifact(root, path):
    return dict(path=str(path.relative_to(root)), bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


class Evidence:
    def __init__(self, root):
        self.root = root
        self.specs = schedule(["detector", "system"], "combined_pipeline")
        self.payload = dict(matrix="combined_pipeline", engine_info=dict(sha256=ENGINE_SHA256),
                            expected_runtime={"fixture": True}, packet_observation=True, files=[],
                            schedule_sha256=hashlib.sha256(json.dumps(self.specs, sort_keys=True).encode()).hexdigest(),
                            plan={"max_bracket_drift_percent": 3})
        write(root / "performance_manifest.json", self.payload)
        self.fingerprint = artifact(root, root / "performance_manifest.json")["sha256"]
        self.jobs = []

    def add(self, spec, attempt=1):
        job = copy.deepcopy(spec)
        output = self.root / (spec["name"] + "_attempt%d" % attempt)
        output.mkdir()
        value = {"R0": 10, "A2": 8, "R4_AB": 7, "R5_ABC": 6}[spec["variant"]]
        rows = []
        for index in range(2):
            row = dict(sample=index, left_candidates=1, right_candidates=1,
                       a2_pack_method_ms=.1 if spec["variant"] != "R0" else 0)
            if spec["scope"] == "detector":
                row.update(detector_wall_ms=value + index * 2, candidates_to_cpu_method_ms=.5)
            else:
                row.update(cycle_start=index * 60, cycle_end=index * 60 + .1,
                           publish_end=index * 60 + .09, cycle_ms=value + index * 2,
                           detector_ms=value + index * 2, read_ready_to_publish_ms=value + index * 2,
                           frame_idx=100 + index, frame_timestamp_s=1 + index,
                           measurement_valid=1, tracking_valid=1, track_initialized=1,
                           coasting=0, frames_since_measurement=0)
            rows.append(row)
        with (output / "frames.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, list(rows[0])); writer.writeheader(); writer.writerows(rows)
        write(output / "result.json", dict(status="complete", seconds=60, samples=2))
        if spec["scope"] == "detector":
            write(output / "effective_runtime.json", dict(engine_sha256=ENGINE_SHA256, warmup_excluded=100, top_k=5))
        else:
            write(output / "progress.json", dict(warmup_total=100, elapsed=60, completed=2))
            write(output / "deployment_config.json", dict(ros_domain_id="87", parameters=dict(
                yolo_top_k=5, yolo_trt_batch=2, imgsz=640, det_conf=.45)))
        warm, end = {}, {}
        defaults = dict(engine="b0", preprocess="c0", postprocess="a0")
        for key, default in defaults.items():
            state = dict(effective=spec["switches"].get(key, default), fallback_count=0, last_error=None)
            warm[key] = dict(state); end[key] = dict(state)
        if spec["switches"].get("engine") == "graph":
            for state, count in ((warm["engine"], 100), (end["engine"], 102)):
                state.update(calls=count, capture_count=1, replay_count=count, input_update_count=count,
                             output_clone_count=count, disabled_reason=None, cleanup_error=None)
        if spec["switches"].get("preprocess") == "c2":
            for state, count in ((warm["preprocess"], 100), (end["preprocess"], 102)):
                state.update(calls=count, success_count=count, host_buffer_allocations=1)
        if spec["switches"].get("postprocess") == "a2":
            for state, count, milliseconds in ((warm["postprocess"], 100, 1.0), (end["postprocess"], 102, 1.2)):
                state.update(predict_calls=count, packed_batches=count, packed_rows=count * 2,
                             d2h_calls=count, d2h_bytes=count * 48, pack_wall_ms_total=milliseconds)
        hook = dict(validation_errors=[], runtime_identity=[self.payload["expected_runtime"]],
                    warmup_checkpoint=[{"components": warm}],
                    detectors=[dict(before_restore={"components": end}, restore="complete")])
        if spec["scope"] == "system":
            hook["packet_observer"] = dict(restore="complete", warmup_calls=100, calls=102,
                fields=["frame_idx", "frame_timestamp_s", "measurement_valid", "tracking_valid",
                        "track_initialized", "coasting", "frames_since_measurement"])
        hooks = self.root / (output.name + "_hooks.json"); write(hooks, hook)
        beginning = datetime.datetime(2026, 10, 22, tzinfo=datetime.timezone.utc)
        beginning += datetime.timedelta(seconds=self.specs.index(spec) * 180 + (attempt - 1) * 3600)
        job.update(attempt=attempt, status="complete", returncode=0, samples=2, output="/robot/" + output.name,
                   started_utc=beginning.isoformat(), completed_utc=(beginning + datetime.timedelta(seconds=120)).isoformat(),
                   payload_sha256=self.fingerprint, metrics=summarize(output / "frames.csv", spec["scope"]),
                   artifacts=[artifact(self.root, p) for p in list(output.iterdir()) + [hooks]])
        self.jobs.append(job)
        return job

    def seal(self):
        write(self.root / "performance_jobs.json", self.jobs)
        write(self.root / "interrupted_recovery_v1_integrity.json",
              dict(errors=[], performance_manifest_sha256=self.fingerprint))
        files = [artifact(self.root, p) for p in self.root.rglob("*") if p.is_file()
                 and p.name not in ("interrupted_recovery_v1_integrity.json", "interrupted_recovery_v1_manifest.json")]
        write(self.root / "interrupted_recovery_v1_manifest.json", {"files": files})


class CombinedReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.evidence = Evidence(self.root)

    def block(self, scope, round_index=1):
        return [self.evidence.add(s) for s in self.evidence.specs if s["scope"] == scope and s["round"] == round_index]

    def test_partial_system_is_retained_but_excluded_from_all_pools_and_pairs(self):
        for number in (1, 2, 3): self.block("detector", number)
        for s in [s for s in self.evidence.specs if s["scope"] == "system"][:4]: self.evidence.add(s)
        failed = copy.deepcopy(self.evidence.specs[19])
        failed.update(attempt=1, status="failed_requires_review", payload_sha256=self.evidence.fingerprint)
        self.evidence.jobs.append(failed); self.evidence.seal()
        result = review(self.root)
        self.assertTrue(result["validation_passed"], result["errors"])
        self.assertEqual(result["status"], "partial_collection_review")
        self.assertEqual(len(result["verified_blocks"]), 3)
        self.assertEqual(result["pools"]["system"], {})
        self.assertEqual(len(result["complete_jobs_excluded_from_pairing"]), 4)
        self.assertEqual(result["paired_macro"]["detector"]["R4_vs_A2"]["independent_blocks"], 3)
        self.assertEqual(result["paired_macro"]["detector"]["R4_vs_A2"]["latency"]["detector_wall_ms"]["mean"]["saved_ms"], 1)
        self.assertFalse(result["production_adopted"])

    def test_full_matrix_handles_nested_packet_metrics_and_per_process_hz(self):
        for spec in self.evidence.specs: self.evidence.add(spec)
        self.evidence.seal(); result = review(self.root)
        self.assertEqual(result["status"], "collection_review")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["pools"]["system"]["A2"]["metrics"]["packet_flags"]["tracking_valid"]["fraction"], 1)
        self.assertAlmostEqual(result["pools"]["system"]["A2"]["metrics"]["processing_hz"], 2 / 60.1)

    def test_superseded_and_failed_history_allow_one_new_complete_attempt(self):
        jobs = self.block("detector")
        for previous in jobs:
            previous.update(status="superseded_incomplete_block", prior_status="complete")
        for spec in self.evidence.specs[:5]:
            self.evidence.add(spec, attempt=2)
        failed = copy.deepcopy(self.evidence.specs[5]); failed.update(attempt=1, status="failed_requires_review", payload_sha256=self.evidence.fingerprint)
        self.evidence.jobs.append(failed); self.evidence.seal()
        result = review(self.root)
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["verified_blocks"]), 1)
        self.assertEqual(len(result["historical_attempts"]), 6)

    def test_duplicate_complete_attempt_rejects_the_entire_block(self):
        self.block("detector"); self.evidence.add(self.evidence.specs[1], attempt=2); self.evidence.seal()
        result = review(self.root)
        self.assertFalse(result["validation_passed"])
        self.assertEqual(result["verified_blocks"], [])
        self.assertTrue(any("Multiple complete" in e["error"] for e in result["errors"]))

    def test_csv_changed_after_artifact_hash_cannot_enter_pairing(self):
        jobs = self.block("detector")
        output = self.root / Path(jobs[1]["output"]).name
        with (output / "frames.csv").open("a") as stream: stream.write("\n")
        self.evidence.seal(); result = review(self.root)
        self.assertFalse(result["validation_passed"])
        self.assertEqual(result["pools"]["detector"], {})

    def test_nested_packet_metric_tamper_is_detected(self):
        jobs = self.block("system")
        jobs[1]["metrics"]["packet_flags"]["measurement_valid"]["fraction"] = .5
        self.evidence.seal(); result = review(self.root)
        self.assertFalse(result["validation_passed"])
        self.assertTrue(any("packet_flags.measurement_valid.fraction" in e["error"] for e in result["errors"]))

    def test_fixed_pair_requires_48_bytes_per_measured_batch(self):
        jobs = self.block("detector")
        hook_path = self.root / (Path(jobs[1]["output"]).name + "_hooks.json")
        hook = json.loads(hook_path.read_text())
        hook["detectors"][0]["before_restore"]["components"]["postprocess"]["d2h_bytes"] += 24
        write(hook_path, hook)
        jobs[1]["artifacts"] = [artifact(self.root, self.root / item["path"]) for item in jobs[1]["artifacts"]]
        self.evidence.seal(); result = review(self.root)
        self.assertFalse(result["validation_passed"])
        self.assertTrue(any("D2H rows/bytes" in e["error"] for e in result["errors"]))

    def test_retry_after_old_bracket_endpoint_cannot_form_a_valid_block(self):
        jobs = self.block("detector")
        jobs[1].update(status="superseded_incomplete_block")
        self.evidence.add(self.evidence.specs[1], attempt=2)
        self.evidence.seal(); result = review(self.root)
        self.assertFalse(result["validation_passed"])
        self.assertEqual(result["verified_blocks"], [])
        self.assertTrue(any("stale and retried" in e["error"] for e in result["errors"]))

    def test_frozen_schedule_hash_is_required(self):
        self.evidence.payload["schedule_sha256"] = "changed"
        write(self.root / "performance_manifest.json", self.evidence.payload)
        self.evidence.seal()
        with self.assertRaisesRegex(ValueError, "Frozen schedule"):
            review(self.root)


if __name__ == "__main__":
    unittest.main()
