#!/usr/bin/env python3
"""Apply reviewed box proposals while preserving concurrent manual work.

Default mode is read-only. --apply invokes the native Qt lock runner, then
persists pending metadata before replacing any label. Images/YAML are never
written. Only complete replacement labels are accepted, so unchanged boxes in
multi-object files must be retained. The baseline must contain per-label SHA256.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

HERE = Path(__file__).resolve().parent
REVIEW_FIELDS = ("annotation_status", "label_review_required", "label_review_note")
REQUIRED = ("图片", "split", "annotation_status", "label_review_required", "label_review_note")
PENDING_STATUS = "auto_label_needs_review"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def entries(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "records" in data:
        return data["records"]
    if isinstance(data, dict):
        return [dict(value, filename=key) for key, value in data.items()]
    raise ValueError("Inventory/proposals must be a list or filename-keyed mapping")


def name_of(row):
    name = row.get("filename", row.get("图片"))
    if not isinstance(name, str) or not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError(f"Unsafe image filename: {name!r}")
    return name


def indexed(data):
    result = {}
    for row in entries(data):
        name = name_of(row)
        if name in result:
            raise ValueError(f"Duplicate filename: {name}")
        result[name] = row
    return result


def regular_under(path: Path, root: Path):
    """Refuse symlinks and paths escaping the selected dataset."""
    resolved = root.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path outside dataset: {path}") from exc
    current = root
    if root.is_symlink():
        raise ValueError(f"Symlink dataset root: {root}")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Symlink is not permitted: {current}")
    if not path.resolve().is_relative_to(resolved) or not path.is_file():
        raise ValueError(f"Missing/unsafe regular file: {path}")
    return path


def csv_parts(data: bytes):
    bom = data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    if "\x00" in text:
        raise ValueError("CSV contains a NUL character")
    # Split physical record boundaries only outside quoted fields. Preserve raw
    # bytes of unaffected records, each record's newline and any UTF-8 BOM.
    records, endings = [], []
    quoted, start, i = False, 0, 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            if quoted and i + 1 < len(text) and text[i + 1] == '"':
                i += 2
                continue
            quoted = not quoted
        elif not quoted and ch in "\r\n":
            end = i + (2 if ch == "\r" and i + 1 < len(text) and text[i + 1] == "\n" else 1)
            records.append(text[start:i])
            endings.append(text[i:end])
            start, i = end, end
            continue
        i += 1
    if quoted:
        raise ValueError("Unterminated quoted CSV field")
    if start < len(text):
        records.append(text[start:]); endings.append("")
    values = [next(csv.reader(io.StringIO(record), strict=True)) for record in records]
    if not values:
        raise ValueError("Empty metadata CSV")
    headers = values[0]
    if len(headers) != len(set(headers)) or any(not x for x in headers):
        raise ValueError("Empty/duplicate CSV header")
    if not set(REQUIRED).issubset(headers):
        raise ValueError(f"CSV is missing columns: {set(REQUIRED) - set(headers)}")
    rows = []
    names = set()
    for values_row in values[1:]:
        if len(values_row) != len(headers):
            raise ValueError("CSV row width mismatch")
        row = dict(zip(headers, values_row))
        name = name_of(row)
        if name in names or row["split"] not in ("train", "val", "test"):
            raise ValueError(f"Duplicate image/invalid split: {name}")
        names.add(name); rows.append(row)
    return {"bom": bom, "headers": headers, "rows": rows, "records": records, "endings": endings}


def csv_update(parsed, replacements):
    out = parsed["records"][0] + parsed["endings"][0]
    for index, row in enumerate(parsed["rows"], 1):
        if row["图片"] in replacements:
            writer_buffer = io.StringIO(newline="")
            writer = csv.writer(writer_buffer, lineterminator="\r\n")
            writer.writerow([replacements[row["图片"]][key] for key in parsed["headers"]])
            record = writer_buffer.getvalue()[:-2]
        else:
            record = parsed["records"][index]
        out += record + parsed["endings"][index]
    return (b"\xef\xbb\xbf" if parsed["bom"] else b"") + out.encode("utf-8")


def label_boxes(data: bytes, *, allow_out_of_bounds=False, boundary_tolerance=1e-7):
    boxes = []
    for line in data.decode("utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5 or not re.fullmatch(r"\d+", parts[0]):
            raise ValueError(f"Invalid YOLO label row: {line!r}")
        cls = int(parts[0]); x, y, w, h = (float(v) for v in parts[1:])
        if cls != 0 or not all(math.isfinite(v) for v in (x, y, w, h)) or not (w > 0 and h > 0):
            raise ValueError(f"Invalid football YOLO box: {line!r}")
        if not allow_out_of_bounds and not (0 <= x <= 1 and 0 <= y <= 1 and w <= 1 and h <= 1):
            raise ValueError(f"Invalid normalized football YOLO box: {line!r}")
        eps = boundary_tolerance
        if not allow_out_of_bounds and not (-eps <= x - w/2 and x + w/2 <= 1 + eps and -eps <= y - h/2 and y + h/2 <= 1 + eps):
            raise ValueError(f"Box crosses image boundary: {line!r}")
        boxes.append([cls, x, y, w, h])
    return boxes


def replacement_bytes(proposal, baseline):
    text = proposal.get("replacement_label")
    if text is None:
        xyxy = proposal.get("boxes_xyxy")
        if xyxy is None:
            raise ValueError("Proposal needs replacement_label or boxes_xyxy")
        width, height = int(baseline["width"]), int(baseline["height"])
        if width <= 0 or height <= 0:
            raise ValueError("Invalid baseline image dimensions")
        lines = []
        for box in xyxy:
            x1, y1, x2, y2 = map(float, box)
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                raise ValueError(f"Invalid pixel box: {box}")
            lines.append(f"0 {(x1+x2)/(2*width):.10f} {(y1+y2)/(2*height):.10f} {(x2-x1)/width:.10f} {(y2-y1)/height:.10f}")
        text = "\n".join(lines) + ("\n" if lines else "")
    if not isinstance(text, str):
        raise ValueError("replacement_label must be a string")
    data = text.encode("utf-8")
    explicit_correction = (proposal.get("action") == "correct_false_positive_or_missing_ball"
                           and proposal.get("native_visual_review") is True)
    if not label_boxes(data) and not explicit_correction:
        raise ValueError("Box audit may not erase all balls")
    return data


def expected_sha(baseline, proposal):
    baseline_sha = baseline.get("label_sha256", baseline.get("old_label_sha256"))
    proposed_sha = proposal.get("expected_label_sha256", baseline_sha)
    if not isinstance(baseline_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", baseline_sha):
        raise ValueError("Baseline lacks a valid per-label SHA256")
    if proposed_sha != baseline_sha:
        raise ValueError("Proposal label SHA disagrees with audited baseline")
    return baseline_sha


def make_plan(root, baseline, proposals):
    root = root.absolute()
    metadata = regular_under(root / "metadata.csv", root)
    metadata_bytes = metadata.read_bytes()
    parsed = csv_parts(metadata_bytes)
    latest = {row["图片"]: row for row in parsed["rows"]}
    accepted, skipped = [], []
    for name, proposal in proposals.items():
        record = {"filename": name}
        try:
            base = baseline[name]
            row = latest[name]
            base_meta = base.get("meta", base)
            split = base_meta.get("split", base.get("split"))
            if split != row["split"] or (proposal.get("split", split) != split):
                raise ValueError("Metadata split changed")
            # A fresh GUI approval is significant even when label bytes match.
            if any(row.get(key, "") != base_meta.get(key, "") for key in REVIEW_FIELDS):
                raise ValueError("Manual review state/note changed after baseline")
            label = regular_under(root / "labels" / split / (Path(name).stem + ".txt"), root)
            image = regular_under(root / "images" / split / name, root)
            original = label.read_bytes()
            sha = expected_sha(base, proposal)
            if digest(original) != sha:
                raise ValueError("Label changed after audited baseline")
            image_sha = base.get("image_sha256")
            if image_sha and digest(image.read_bytes()) != image_sha:
                raise ValueError("Image changed after audited baseline")
            replacement = replacement_bytes(proposal, base)
            explicit_correction = (proposal.get("action") == "correct_false_positive_or_missing_ball"
                                   and proposal.get("native_visual_review") is True)
            # A native visual correction may repair an invalid old boundary.
            # Replacement labels always use the strict in-image parser.
            old_boxes = label_boxes(original, allow_out_of_bounds=explicit_correction)
            new_boxes = label_boxes(replacement)
            if len(old_boxes) != len(new_boxes) and not explicit_correction:
                raise ValueError("Box audit may not change target count")
            for old, new in zip(old_boxes, new_boxes):
                if new[3]*new[4] > old[3]*old[4] + 1e-8 and not explicit_correction:
                    raise ValueError("Proposal enlarges a box; requires separate review")
            if len(old_boxes) == len(new_boxes) and all(all(abs(a-b) <= 1e-9 for a,b in zip(old,new)) for old,new in zip(old_boxes,new_boxes)):
                skipped.append(dict(record, reason="No coordinate change")); continue
            reason = proposal.get("reason", "")
            source = proposal.get("source", "")
            if not reason or not source:
                raise ValueError("Proposal requires reason and source provenance")
            suffix = (f"2026-10-14 框边界审核：{reason} 来源：{source}；原框SHA256={sha}；"
                      f"原状态={row['annotation_status']}；助手修正候选框，需人工复核。")
            if row.get("No Ball") == "1" and new_boxes:
                suffix += " 当前No Ball=1与非空球框冲突；保留最新分类值，请人工核对分类与候选框。"
            if row.get("No Ball") != "1" and not new_boxes:
                suffix += " 已移除明确误框，当前空label与No Ball=0需要人工核对；保留最新分类值。"
            pending = dict(row)
            pending.update(annotation_status=PENDING_STATUS, label_review_required="1",
                           label_review_note=(row["label_review_note"] + " " + suffix).strip())
            if ((row.get("No Ball") == "1" and new_boxes)
                    or (row.get("No Ball") != "1" and not new_boxes)) and "scene_review_required" in pending:
                pending["scene_review_required"] = "1"
            if len(old_boxes) != len(new_boxes) and "auto_box_count" in pending:
                pending["auto_box_count"] = str(len(new_boxes))
            accepted.append(dict(record, split=split, path=label, image_path=image,
                                 original=original, replacement=replacement, before_sha256=sha,
                                 after_sha256=digest(replacement), old_boxes=old_boxes, new_boxes=new_boxes,
                                 original_meta=dict(row), pending_meta=pending, reason=reason, source=source))
        except (KeyError, ValueError, OSError, UnicodeError) as exc:
            skipped.append(dict(record, reason=str(exc)))
    return metadata, metadata_bytes, parsed, accepted, skipped


def save_exclusive(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())


def atomic_replace(path, data, expected):
    """Prepare/fsync before a second byte comparison; preserve mode on rename."""
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.box-audit-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, stat.S_IMODE(path.stat().st_mode))
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        if path.read_bytes() != expected:
            raise RuntimeError(f"File changed during save; refusing overwrite: {path}")
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def public_record(record):
    return {key: (str(value) if isinstance(value, Path) else value)
            for key, value in record.items() if key not in ("original", "replacement")}


def apply_locked(root, baseline, proposals, audit_root):
    metadata, original_csv, parsed, accepted, skipped = make_plan(root, baseline, proposals)
    run = audit_root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    run.mkdir(parents=True, exist_ok=False)
    plan = {"dataset": str(root), "metadata_before_sha256": digest(original_csv),
            "accepted": [public_record(row) for row in accepted], "skipped": skipped}
    save_exclusive(run / "plan.json", json.dumps(plan, ensure_ascii=False, indent=2).encode())
    if not accepted:
        save_exclusive(run / "result.json", json.dumps({"applied": [], "skipped": skipped}).encode())
        return {"audit": str(run), "applied": 0, "skipped": len(skipped)}
    # All backups are complete before production mutation starts.
    save_exclusive(run / "before" / "metadata.csv", original_csv, stat.S_IMODE(metadata.stat().st_mode))
    for item in accepted:
        save_exclusive(run / "before" / "labels" / item["split"] / item["path"].name,
                       item["original"], stat.S_IMODE(item["path"].stat().st_mode))
        save_exclusive(run / "proposed" / "labels" / item["split"] / item["path"].name, item["replacement"])
    # Check every label again before metadata pending. Non-cooperating edits
    # after the locks were taken are skipped rather than overwritten.
    ready = []
    for item in accepted:
        if item["path"].read_bytes() != item["original"]:
            skipped.append({"filename": item["filename"], "reason": "Label changed during preparation"})
        else:
            ready.append(item)
    replacement_csv = csv_update(parsed, {row["filename"]: row["pending_meta"] for row in ready})
    atomic_replace(metadata, replacement_csv, original_csv)
    applied, failed = [], []
    for item in ready:
        try:
            atomic_replace(item["path"], item["replacement"], item["original"])
            applied.append(public_record(item))
        except (OSError, RuntimeError) as exc:
            # The row deliberately stays pending when label replacement fails.
            failed.append({"filename": item["filename"], "reason": str(exc)})
    result = {"applied": applied, "skipped": skipped, "failed_pending": failed,
              "metadata_after_sha256": digest(metadata.read_bytes())}
    save_exclusive(run / "result.json", json.dumps(result, ensure_ascii=False, indent=2).encode())
    return {"audit": str(run), "applied": len(applied), "skipped": len(skipped), "failed_pending": len(failed)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--audit-root", type=Path, default=HERE / "apply-audits")
    parser.add_argument("--lock-runner", type=Path, default=HERE / "qt_review_lock_runner")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--locked", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--baseline-sha", help=argparse.SUPPRESS)
    parser.add_argument("--proposals-sha", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = args.dataset.absolute()
    baseline_bytes, proposals_bytes = args.baseline.read_bytes(), args.proposals.read_bytes()
    if args.baseline_sha and digest(baseline_bytes) != args.baseline_sha:
        raise SystemExit("Baseline changed while acquiring review locks")
    if args.proposals_sha and digest(proposals_bytes) != args.proposals_sha:
        raise SystemExit("Proposals changed while acquiring review locks")
    baseline = indexed(json.loads(baseline_bytes))
    proposals = indexed(json.loads(proposals_bytes))
    if args.locked:
        print(json.dumps(apply_locked(root, baseline, proposals, args.audit_root), ensure_ascii=False))
        return
    metadata, current, parsed, accepted, skipped = make_plan(root, baseline, proposals)
    summary = {"mode": "dry_run", "accepted": len(accepted), "skipped": skipped,
               "metadata_sha256": digest(current), "accepted_filenames": [r["filename"] for r in accepted]}
    if not args.apply:
        print(json.dumps(summary, ensure_ascii=False, indent=2)); return
    if not args.lock_runner.is_file():
        raise SystemExit("Compile qt_review_lock_runner.cpp against local Qt6Core before --apply")
    # The same ordering as the GUI: labels first, then metadata. tryLock(0)
    # aborts immediately if another review save is in progress; no lock removal.
    # Lock all valid proposal paths, including currently skipped ones: a row
    # must not become eligible in the second plan without its label lock.
    proposal_paths = []
    for name in proposals:
        base = baseline.get(name, {})
        split = base.get("meta", base).get("split", base.get("split"))
        if split in ("train", "val", "test"):
            path = root / "labels" / split / (Path(name).stem + ".txt")
            if path.parent.is_dir() and not any(p.is_symlink() for p in (path, path.parent, path.parent.parent, root)):
                proposal_paths.append(path)
    lock_paths = [str(path) + ".review.lock" for path in sorted(set(proposal_paths))]
    lock_paths.append(str(metadata) + ".review.lock")
    args.audit_root.mkdir(parents=True, exist_ok=True)
    lock_list = args.audit_root / ("locks-" + uuid4().hex + ".json")
    save_exclusive(lock_list, json.dumps(lock_paths).encode())
    command = [str(args.lock_runner), "--lock-list", str(lock_list), "--", sys.executable, str(Path(__file__).resolve()),
               "--dataset", str(root), "--baseline", str(args.baseline.absolute()), "--proposals", str(args.proposals.absolute()),
               "--audit-root", str(args.audit_root.absolute()), "--baseline-sha", digest(baseline_bytes),
               "--proposals-sha", digest(proposals_bytes), "--locked"]
    try:
        raise SystemExit(subprocess.run(command).returncode)
    finally:
        lock_list.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
