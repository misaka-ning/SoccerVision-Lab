#!/usr/bin/env python3
"""Read-only football dataset checks; Python standard library only.

Success means structural validity, not visual verification or training approval.
The helper writes nothing unless --report is explicitly supplied.
"""

import argparse
import collections
import csv
import json
import math
import os
from pathlib import Path
import re
import sys


FLAGS = ("Small", "Occluded", "Blurred", "No Ball")
REVIEW_FLAGS = ("scene_review_required", "label_review_required")
CORE_COLUMNS = ("图片",) + FLAGS + (
    "split", "annotation_status", "scene_review_required", "label_review_required"
)
OPTIONAL_COLUMNS = (
    "auto_box_count", "preserved_box_count", "label_review_note",
    "source_video", "source_frame_idx", "eye"
)
SPLITS = {"train", "val", "test"}
PENDING_STATUSES = {
    "auto_label_needs_review", "needs_visibility_review",
    "needs_manual_bbox_annotation"
}
STATUSES = PENDING_STATUSES | {
    "negative_confirmed", "provided_annotation", "reviewed_annotation"
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
NONNEGATIVE_INTEGER = re.compile(r"[0-9]+\Z")
# Six-decimal imported GT may round an image-edge coordinate by half a unit.
BOUNDARY_TOLERANCE = 1e-6


def validate_dataset(dataset):
    root = Path(dataset).expanduser().absolute()
    errors, warnings = [], []
    statistics = {
        "rows": 0, "image_files": 0, "label_files": 0,
        "label_kinds": {"nonempty": 0, "empty": 0, "missing": 0},
        "boxes": 0, "split_counts": {}, "annotation_status_counts": {},
        "scene_flag_counts": {}, "pending_label_rows": 0,
        "pending_scene_rows": 0, "pending_any_review_rows": 0,
        "confirmed_rows_without_pending_review": 0,
        "source_frame_groups": 0,
    }
    report = {
        "success": False, "dataset": str(root), "read_only": True,
        "training_ready": False,
        "training_ready_note": (
            "Pending label/scene rows must be excluded from a training subset. "
            "Structural validation does not approve candidates or verify visual "
            "quality; dataset.yaml must also be checked manually."
        ),
        "yaml": {"exists": False, "fully_parsed": False,
                 "manual_configuration_check_required": True},
        "metadata": {}, "statistics": statistics,
        "errors": errors, "warnings": warnings,
    }

    def issue(target, code, message, row=None, image=None, path=None):
        item = {"code": code, "message": message}
        if row is not None:
            item["csv_record"] = row
        if image is not None:
            item["image"] = image
        if path is not None:
            item["path"] = str(path)
        target.append(item)

    def error(code, message, **context):
        issue(errors, code, message, **context)

    def warning(code, message, **context):
        issue(warnings, code, message, **context)

    if not root.is_dir():
        error("dataset_missing", "Dataset directory does not exist.", path=root)
        return report
    yaml_path = root / "dataset.yaml"
    report["yaml"]["exists"] = yaml_path.is_file()
    if not yaml_path.is_file():
        error("yaml_missing", "dataset.yaml is required.", path=yaml_path)
    else:
        try:
            if not yaml_path.read_text(encoding="utf-8-sig").strip():
                error("yaml_empty", "dataset.yaml is empty.", path=yaml_path)
        except (OSError, UnicodeError) as exc:
            error("yaml_unreadable", str(exc), path=yaml_path)
        warning(
            "yaml_manual_check",
            "YAML is not fully parsed by this standard-library helper. Manually "
            "verify path, split paths, and the single class 0 football mapping.",
            path=yaml_path,
        )

    metadata_path = root / "metadata.csv"
    try:
        with metadata_path.open(encoding="utf-8-sig", newline="") as stream:
            records = list(csv.reader(stream, strict=True))
    except (OSError, UnicodeError, csv.Error) as exc:
        error("metadata_unreadable", str(exc), path=metadata_path)
        return report
    if not records or not records[0]:
        error("metadata_empty", "CSV is empty or has no header.", path=metadata_path)
        return report
    headers = records[0]
    report["metadata"] = {
        "columns": headers,
        "unknown_columns_preserved": [
            h for h in headers if h not in CORE_COLUMNS + OPTIONAL_COLUMNS
        ],
        "optional_columns_absent": [h for h in OPTIONAL_COLUMNS if h not in headers],
        "rewritten": False,
    }
    if len(headers) != len(set(headers)):
        error("duplicate_header", "CSV column names must be unique.")
        return report
    if any(not h for h in headers):
        error("empty_header", "CSV contains an empty column name.")
        return report
    absent = [h for h in CORE_COLUMNS if h not in headers]
    if absent:
        error("missing_columns", "Required columns are missing: " + ", ".join(absent))
        return report
    if len(records) == 1:
        error("metadata_no_rows", "CSV has a header but no image rows.")

    rows = []
    for number, values in enumerate(records[1:], start=2):
        if len(values) != len(headers):
            error("csv_column_count", "CSV record has an incorrect column count.", row=number)
            continue
        rows.append((number, dict(zip(headers, values))))
    statistics["rows"] = len(rows)
    splits, statuses, scene_counts = collections.Counter(), collections.Counter(), collections.Counter()
    filenames, stems = {}, {}
    expected_images, expected_labels = set(), set()
    source_groups = collections.defaultdict(list)

    for number, row in rows:
        name, split, status = row["图片"], row["split"], row["annotation_status"]
        context = {"row": number, "image": name}
        row_error_count = len(errors)
        splits[split] += 1
        statuses[status] += 1
        for field in FLAGS + REVIEW_FLAGS:
            if row[field] not in {"0", "1"}:
                error("nonbinary_field", field + " must be exactly 0 or 1.", **context)
        for field in FLAGS:
            if row[field] == "1":
                scene_counts[field] += 1
        review_pending = row["label_review_required"] == "1"
        scene_pending = row["scene_review_required"] == "1"
        statistics["pending_label_rows"] += int(review_pending)
        statistics["pending_scene_rows"] += int(scene_pending)
        statistics["pending_any_review_rows"] += int(review_pending or scene_pending)
        if split not in SPLITS:
            error("invalid_split", "split must be train, val, or test.", **context)
        if status not in STATUSES:
            error("invalid_status", "Unknown annotation_status: " + status, **context)
        if status in PENDING_STATUSES and not review_pending:
            error("pending_status_without_review", "Pending annotation status requires label_review_required=1.", **context)
        if status in {"negative_confirmed", "reviewed_annotation"} and review_pending:
            error("confirmed_status_pending", "Confirmed annotation status requires label_review_required=0.", **context)
        for field in ("auto_box_count", "preserved_box_count"):
            if field in row and not NONNEGATIVE_INTEGER.fullmatch(row[field]):
                error("invalid_provenance_count", field + " must be a nonnegative integer; it is not compared with current boxes.", **context)

        safe_name = bool(name) and name not in {".", ".."} and "/" not in name and "\\" not in name and "\x00" not in name
        if not safe_name:
            error("unsafe_filename", "图片 must be a plain, nonempty filename.", **context)
        elif Path(name).suffix.lower() not in IMAGE_EXTENSIONS:
            error("unsupported_image_extension", "Unsupported image filename extension.", **context)
        if name in filenames:
            error("duplicate_filename", "Filename is not globally unique; first record " + str(filenames[name]) + ".", **context)
        filenames[name] = number
        if safe_name:
            stem = Path(name).stem
            if stem in stems:
                error("duplicate_stem", "Image stem is not globally unique; labels would collide with " + stems[stem] + ".", **context)
            stems[stem] = name

        source = row.get("source_video", "")
        frame = row.get("source_frame_idx", "")
        eye = row.get("eye", "")
        if source or frame or eye:
            if not source or not Path(source).is_absolute():
                error("invalid_source_video", "Nonempty provenance requires an absolute source_video path.", **context)
            if not NONNEGATIVE_INTEGER.fullmatch(frame):
                error("invalid_source_frame", "source_frame_idx must be a nonnegative zero-based integer.", **context)
            if eye not in {"left", "right", "mono"}:
                error("invalid_eye", "eye must be left, right, or mono.", **context)
            if source and Path(source).is_absolute() and NONNEGATIVE_INTEGER.fullmatch(frame):
                source_groups[(os.path.normpath(source), int(frame))].append((name, split, eye, number))

        if not safe_name or split not in SPLITS:
            continue
        image_path = root / "images" / split / name
        label_path = root / "labels" / split / (Path(name).stem + ".txt")
        expected_images.add(image_path.relative_to(root).as_posix())
        expected_labels.add(label_path.relative_to(root).as_posix())
        if not image_path.is_file():
            error("image_missing", "Metadata image is missing at the matching split path.", path=image_path, **context)

        note = row.get("label_review_note", "").strip()
        allow_pending_conflict = review_pending and bool(note)
        # Whole-image motion blur can coexist with a confirmed negative.
        # Small/Occluded describe balls, so conflicts need documented review.
        if row["No Ball"] == "1" and any(row[f] == "1" for f in ("Small", "Occluded")):
            allow_scene_conflict = bool(note) and (scene_pending or review_pending)
            destination = warning if allow_scene_conflict else error
            destination("no_ball_scene_conflict", "No Ball=1 conflicts with Small/Occluded; preserve only as a documented pending scene or label review. Whole-image Blurred=1 remains valid with No Ball=1.", **context)

        if not label_path.is_file():
            statistics["label_kinds"]["missing"] += 1
            if status in PENDING_STATUSES and review_pending:
                warning("missing_label_pending", "Missing label is pending review, not a confirmed negative or training-ready sample.", path=label_path, **context)
            else:
                error("missing_label_not_pending", "Missing label is allowed only with a pending annotation status and label_review_required=1.", path=label_path, **context)
            continue
        try:
            text = label_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            error("label_unreadable", str(exc), path=label_path, **context)
            continue
        lines = [(n, line) for n, line in enumerate(text.splitlines(), start=1) if line.strip()]
        kind = "nonempty" if lines else "empty"
        statistics["label_kinds"][kind] += 1
        if kind == "empty" and row["No Ball"] != "1":
            destination = warning if allow_pending_conflict else error
            destination("empty_label_ball_conflict", "Empty label with No Ball=0 requires a documented pending conflict and must not enter training.", path=label_path, **context)
        if kind == "nonempty" and row["No Ball"] == "1":
            destination = warning if allow_pending_conflict else error
            destination("positive_label_no_ball_conflict", "Ball boxes with No Ball=1 require a documented pending human conflict and must not enter training.", path=label_path, **context)
        if status == "negative_confirmed" and (kind != "empty" or row["No Ball"] != "1"):
            error("invalid_confirmed_negative", "negative_confirmed requires an empty label and No Ball=1.", **context)
        if status == "reviewed_annotation" and kind != "nonempty":
            error("invalid_reviewed_annotation", "reviewed_annotation requires a nonempty football label.", **context)
        if status in PENDING_STATUSES and kind == "empty":
            warning("empty_label_pending", "Empty label remains pending; do not treat it as confirmed background.", **context)

        for line_number, line in lines:
            values = line.split()
            if len(values) != 5 or values[0] != "0":
                error("invalid_yolo_columns_or_class", "YOLO line " + str(line_number) + " must have class 0 and exactly five columns.", path=label_path, **context)
                continue
            try:
                x, y, width, height = map(float, values[1:])
            except ValueError:
                error("invalid_yolo_number", "Non-numeric YOLO coordinate at line " + str(line_number) + ".", path=label_path, **context)
                continue
            if not all(math.isfinite(v) for v in (x, y, width, height)):
                error("nonfinite_yolo_coordinate", "YOLO coordinates must be finite at line " + str(line_number) + ".", path=label_path, **context)
                continue
            if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < width <= 1 and 0 < height <= 1):
                error("invalid_yolo_coordinate_range", "YOLO centers must lie in [0,1] and dimensions in (0,1] at line " + str(line_number) + ".", path=label_path, **context)
                continue
            tolerance = BOUNDARY_TOLERANCE
            if x - width / 2 < -tolerance or y - height / 2 < -tolerance or x + width / 2 > 1 + tolerance or y + height / 2 > 1 + tolerance:
                error("yolo_box_outside_image", "YOLO box crosses image bounds at line " + str(line_number) + ".", path=label_path, **context)
                continue
            statistics["boxes"] += 1
        if len(errors) == row_error_count and not review_pending and not scene_pending and status in {"provided_annotation", "reviewed_annotation", "negative_confirmed"}:
            statistics["confirmed_rows_without_pending_review"] += 1

    for (source, frame), group in source_groups.items():
        if len({item[1] for item in group}) > 1:
            error("source_frame_split_leak", "The same source video/frame, including paired eyes, is spread across splits: " + json.dumps({"source_video": source, "source_frame_idx": frame, "rows": group}, ensure_ascii=False))
    statistics["source_frame_groups"] = len(source_groups)

    for directory, expected, stat_key in (
        ("images", expected_images, "image_files"),
        ("labels", expected_labels, "label_files"),
    ):
        folder = root / directory
        if not folder.is_dir():
            error("directory_missing", directory + " directory is missing.", path=folder)
            continue
        try:
            present = {p.relative_to(root).as_posix() for p in folder.rglob("*") if p.is_file()}
        except OSError as exc:
            error("directory_unreadable", str(exc), path=folder)
            continue
        statistics[stat_key] = len(present)
        for extra in sorted(present - expected):
            error("unreferenced_" + directory + "_file", "File has no matching metadata row at the same split/stem.", path=root / extra)
        # Missing labels were classified per row above; missing images are hard errors.
        if directory == "images":
            physical_names, physical_stems = {}, {}
            for relative in sorted(present):
                path = Path(relative)
                if path.name in physical_names:
                    error("physical_duplicate_filename", "Image filename occurs at multiple paths: " + physical_names[path.name], path=root / relative)
                physical_names[path.name] = relative
                if path.stem in physical_stems:
                    error("physical_duplicate_stem", "Image stem occurs at multiple paths: " + physical_stems[path.stem], path=root / relative)
                physical_stems[path.stem] = relative

    statistics["split_counts"] = dict(sorted(splits.items()))
    statistics["annotation_status_counts"] = dict(sorted(statuses.items()))
    statistics["scene_flag_counts"] = {flag: scene_counts[flag] for flag in FLAGS}
    report["success"] = not errors
    report["structurally_confirmed_subset_covers_all_rows"] = (
        not errors and statistics["rows"] > 0
        and statistics["confirmed_rows_without_pending_review"] == statistics["rows"]
    )
    report["metadata"]["box_count_policy"] = "auto_box_count/preserved_box_count are provenance; never forced to equal current box count."
    report["coordinate_boundary_tolerance"] = BOUNDARY_TOLERANCE
    report["pixel_content_checked"] = False
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="Dataset root containing metadata.csv and dataset.yaml")
    parser.add_argument("--report", help="Optional JSON output path; no files are written when omitted")
    args = parser.parse_args(argv)
    report = validate_dataset(args.dataset)
    if args.report:
        try:
            output = Path(args.report).expanduser()
            dataset = Path(args.dataset).expanduser().resolve()
            resolved_output = output.resolve()
            protected = {dataset / "metadata.csv", dataset / "dataset.yaml"}
            if (resolved_output in protected
                    or dataset / "images" in resolved_output.parents
                    or dataset / "labels" in resolved_output.parents):
                raise OSError("Report output must not overwrite dataset metadata, YAML, images, or labels.")
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            report["success"] = False
            report["errors"].append({"code": "report_write_failed", "message": str(exc), "path": args.report})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
