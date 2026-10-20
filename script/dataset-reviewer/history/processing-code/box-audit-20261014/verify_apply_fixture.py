#!/usr/bin/env python3
"""Small disposable fixture for safety boundaries; never accesses production."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("apply_box_audit", HERE / "apply_box_audit.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fixture(base):
    dataset = base / "dataset"
    labels, images = dataset / "labels" / "train", dataset / "images" / "train"
    labels.mkdir(parents=True); images.mkdir(parents=True)
    rows, inventory, proposals = [], [], []
    old = b"0 0.50000000 0.50000000 0.40000000 0.40000000\n"
    new = "0 0.50000000 0.50000000 0.30000000 0.30000000\n"
    for name in ("ok.png", "label_changed.png", "review_changed.png"):
        row = {"图片": name, "Small": "0", "Occluded": "0", "Blurred": "0", "No Ball": "0",
               "split": "train", "annotation_status": "provided_annotation", "scene_review_required": "0",
               "label_review_required": "0", "label_review_note": "source, original\nsecond line", "unknown": "baseline"}
        (labels / (Path(name).stem + ".txt")).write_bytes(old)
        (images / name).write_bytes(b"fixture-image")
        rows.append(row)
        inventory.append({"filename": name, "meta": dict(row), "width": 100, "height": 100,
                          "label_sha256": sha(old), "image_sha256": sha(b"fixture-image")})
        proposals.append({"filename": name, "expected_label_sha256": sha(old), "replacement_label": new,
                          "reason": "tighten empty margin", "source": "fixture visual audit"})
    (labels / "label_changed.txt").write_bytes(b"0 0.5 0.5 0.2 0.2\n")
    rows[0].update(Small="1", unknown="latest human, unknown value")
    rows[2].update(annotation_status="reviewed_annotation", label_review_note="fresh human approval")
    with (dataset / "metadata.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    for name, data in (("baseline.json", inventory), ("proposals.json", proposals)):
        (base / name).write_text(json.dumps(data))
    return dataset, old, new.encode()


def command(base):
    return [sys.executable, str(HERE / "apply_box_audit.py"), "--dataset", str(base / "dataset"),
            "--baseline", str(base / "baseline.json"), "--proposals", str(base / "proposals.json"),
            "--audit-root", str(base / "audits")]


def inventory_bytes(dataset):
    return {str(p.relative_to(dataset)): p.read_bytes() for p in dataset.rglob("*")
            if p.is_file() and not p.name.endswith(".review.lock")}


def main():
    checks = []
    with tempfile.TemporaryDirectory(prefix="apply-fixture-", dir=HERE) as name:
        base = Path(name)
        dataset, old, new = fixture(base)
        before = inventory_bytes(dataset)
        dry = subprocess.run(command(base), capture_output=True, text=True, check=True)
        dry_result = json.loads(dry.stdout)
        assert dry_result["accepted"] == 1 and len(dry_result["skipped"]) == 2, dry_result
        assert before == inventory_bytes(dataset)
        checks.append("read-only dry-run and stale label/review skips")

        # A real native Qt lock held by another live process must block apply.
        lock_path = dataset / "labels" / "train" / "ok.txt.review.lock"
        list_path = base / "other-locks.json"
        list_path.write_text(json.dumps([str(lock_path)]))
        holder = subprocess.Popen([str(HERE / "qt_review_lock_runner"), "--lock-list", str(list_path),
                                   "--", sys.executable, "-c", "import time; time.sleep(3)"])
        try:
            deadline = time.monotonic() + 2
            while not lock_path.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            assert lock_path.exists()
            blocked = subprocess.run(command(base) + ["--apply"], capture_output=True, text=True)
            assert blocked.returncode == 73, (blocked.returncode, blocked.stdout, blocked.stderr)
            assert before == inventory_bytes(dataset)
        finally:
            holder.wait(timeout=5)
        assert not lock_path.exists()
        checks.append("native QLockFile conflict leaves dataset untouched")

        run = subprocess.run(command(base) + ["--apply"], capture_output=True, text=True, check=True)
        result = json.loads(run.stdout)
        assert result["applied"] == 1 and result["skipped"] == 2 and result["failed_pending"] == 0, result
        latest = module.csv_parts((dataset / "metadata.csv").read_bytes())
        rows = {r["图片"]: r for r in latest["rows"]}
        assert rows["ok.png"]["Small"] == "1" and rows["ok.png"]["unknown"] == "latest human, unknown value"
        assert rows["ok.png"]["annotation_status"] == "auto_label_needs_review"
        assert rows["ok.png"]["label_review_required"] == "1"
        assert sha(old) in rows["ok.png"]["label_review_note"] and "fixture visual audit" in rows["ok.png"]["label_review_note"]
        assert rows["review_changed.png"]["annotation_status"] == "reviewed_annotation"
        after = inventory_bytes(dataset)
        for p, original in before.items():
            if p not in ("metadata.csv", "labels/train/ok.txt"):
                assert after[p] == original, p
        assert (dataset / "labels" / "train" / "ok.txt").read_bytes() == new
        audit = Path(result["audit"])
        assert (audit / "before" / "metadata.csv").read_bytes() == before["metadata.csv"]
        assert (audit / "before" / "labels" / "train" / "ok.txt").read_bytes() == old
        # Unaffected records retain byte-for-byte original quoting/newlines.
        prior = module.csv_parts(before["metadata.csv"])
        assert latest["bom"] and latest["endings"] == prior["endings"]
        assert latest["records"][2:] == prior["records"][2:]
        checks.append("atomic apply, exact backups, current human/unknown fields, pending provenance")

    with tempfile.TemporaryDirectory(prefix="apply-failure-fixture-", dir=HERE) as name:
        base = Path(name); dataset, old, new = fixture(base)
        original_replace = module.atomic_replace
        def fail_label(path, data, expected):
            if path.suffix == ".txt":
                raise OSError("fixture label commit failure")
            return original_replace(path, data, expected)
        module.atomic_replace = fail_label
        try:
            result = module.apply_locked(dataset, module.indexed(module.read_json(base / "baseline.json")),
                                         module.indexed(module.read_json(base / "proposals.json")), base / "audits")
        finally:
            module.atomic_replace = original_replace
        assert result["applied"] == 0 and result["failed_pending"] == 1, result
        assert (dataset / "labels" / "train" / "ok.txt").read_bytes() == old
        rows = module.csv_parts((dataset / "metadata.csv").read_bytes())["rows"]
        assert rows[0]["annotation_status"] == "auto_label_needs_review" and rows[0]["label_review_required"] == "1"
        checks.append("failed label commit retains original label and pending CSV")

    with tempfile.TemporaryDirectory(prefix="atomic-conflict-fixture-", dir=HERE) as name:
        path = Path(name) / "label.txt"
        path.write_bytes(b"latest human bytes")
        try:
            module.atomic_replace(path, b"proposed bytes", b"stale bytes")
            raise AssertionError("Expected final SHA/byte mismatch refusal")
        except RuntimeError:
            assert path.read_bytes() == b"latest human bytes"
        checks.append("final comparison rejects non-cooperating edits")

    with tempfile.TemporaryDirectory(prefix="native-correction-fixture-", dir=HERE) as name:
        base = Path(name); dataset, old, new = fixture(base)
        baseline = module.indexed(module.read_json(base / "baseline.json"))
        proposal = module.read_json(base / "proposals.json")[0]
        proposal["replacement_label"] = ""
        # Routine tightening cannot erase targets, nor can an unverified action.
        for native in (None, False):
            proposal.update(action="correct_false_positive_or_missing_ball", native_visual_review=native)
            plan = module.make_plan(dataset, baseline, {"ok.png": proposal})
            assert len(plan[3]) == 0 and len(plan[4]) == 1
        proposal["native_visual_review"] = True
        proposal["reason"] = "native image confirms shoe false positive"
        result = module.apply_locked(dataset, baseline, {"ok.png": proposal}, base / "audits")
        assert result["applied"] == 1 and result["failed_pending"] == 0
        assert (dataset / "labels" / "train" / "ok.txt").read_bytes() == b""
        row = module.csv_parts((dataset / "metadata.csv").read_bytes())["rows"][0]
        assert row["No Ball"] == "0" and row["Small"] == "1"
        assert row["annotation_status"] == "auto_label_needs_review" and row["label_review_required"] == "1"
        assert row["scene_review_required"] == "1"
        assert "空label" in row["label_review_note"] and "保留最新分类值" in row["label_review_note"]
        assert row["unknown"] == "latest human, unknown value"
        checks.append("explicit native false-positive removal remains pending and preserves class conflicts")

    with tempfile.TemporaryDirectory(prefix="old-bounds-fixture-", dir=HERE) as name:
        base = Path(name); dataset, old, new = fixture(base)
        old = b"0 0.5 0.1 0.3 0.25\n"  # Old y1=-0.025, repairable only after native review.
        (dataset / "labels" / "train" / "ok.txt").write_bytes(old)
        baseline = module.indexed(module.read_json(base / "baseline.json"))
        baseline["ok.png"]["label_sha256"] = sha(old)
        proposal = module.read_json(base / "proposals.json")[0]
        proposal.update(expected_label_sha256=sha(old), replacement_label="0 0.5 0.125 0.3 0.25\n")
        assert not module.make_plan(dataset, baseline, {"ok.png": proposal})[3]
        proposal.update(action="correct_false_positive_or_missing_ball", native_visual_review=True)
        assert len(module.make_plan(dataset, baseline, {"ok.png": proposal})[3]) == 1
        proposal["replacement_label"] = "0 0.5 0.1 0.3 0.25\n"
        assert not module.make_plan(dataset, baseline, {"ok.png": proposal})[3]
        parsed = module.csv_parts((dataset / "metadata.csv").read_bytes())
        latest_row = dict(parsed["rows"][0], **{"No Ball": "1", "Occluded": "1", "Blurred": "1"})
        (dataset / "metadata.csv").write_bytes(module.csv_update(parsed, {"ok.png": latest_row}))
        proposal["replacement_label"] = "0 0.5 0.125 0.3 0.25\n"
        planned = module.make_plan(dataset, baseline, {"ok.png": proposal})[3][0]["pending_meta"]
        assert planned["scene_review_required"] == "1"
        assert [planned[k] for k in ("Small", "Occluded", "Blurred", "No Ball")] == ["1", "1", "1", "1"]
        for malformed in (b"1 0.5 0.1 0.3 0.25\n", b"0 nan 0.1 0.3 0.25\n", b"0 0.5 0.1 -0.3 0.25\n"):
            try:
                module.label_boxes(malformed, allow_out_of_bounds=True)
                raise AssertionError("Native correction must still reject invalid class/numbers/size")
            except ValueError:
                pass
        checks.append("only native corrections repair old out-of-bounds boxes; replacements and syntax remain strict")

    report = {"passed": True, "checks": checks, "production_touched": False}
    (HERE / "apply-fixture-result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
