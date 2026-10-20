#!/usr/bin/env python3
"""Read-only structural validation of the configured reviewed dataset."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'script'))
from common.dataset_config import load_dataset
SPLITS = ("train", "val", "test")
SCENES = ("Small", "Occluded", "Blurred", "No Ball")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
STATUSES = {"reviewed_annotation", "negative_confirmed", "reviewed_excluded"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def filename(value: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."} or any(c in value for c in "/\\\r\n"):
        raise ValueError(f"非法图片文件名：{value!r}")
    return value


def read_metadata(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"图片", "split", "annotation_status", "scene_review_required", "label_review_required", *SCENES}
        if not required <= set(reader.fieldnames or []):
            raise ValueError(f"metadata缺少必要列：{path}")
        rows = {}
        for row in reader:
            name = filename(row["图片"])
            if name in rows:
                raise ValueError(f"metadata图片名重复：{name}")
            rows[name] = row
    return rows


def box_count(path: Path) -> int:
    count = 0
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 5 or fields[0] != "0":
            raise ValueError(f"label须为五列且类别为0：{path}:{number}")
        x, y, w, h = map(float, fields[1:])
        if not all(math.isfinite(v) for v in (x, y, w, h)) or not all(0 <= v <= 1 for v in (x, y, w, h)) or w <= 0 or h <= 0:
            raise ValueError(f"label坐标须有限、归一化且宽高为正：{path}:{number}")
        if min(x - w / 2, y - h / 2) < -1e-6 or max(x + w / 2, y + h / 2) > 1 + 1e-6:
            raise ValueError(f"label角点越界：{path}:{number}")
        count += 1
    return count


def regular_file(path: Path, boundary: Path) -> None:
    """Reject links in the file path, including linked parent directories."""
    path.relative_to(boundary)
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f"数据路径不能是软链接：{part}")
        if part == boundary:
            break
    if not path.is_file():
        raise ValueError(f"缺少普通文件：{path}")


def verify(root: Path = ROOT, *, data=None, config=None, version=None) -> dict:
    errors = []
    error_count = 0

    def error(message):
        nonlocal error_count
        error_count += 1
        if len(errors) < 20:
            errors.append(str(message))

    try:
        data = Path(data) if data is not None else load_dataset(config,version,root=root)['root']
        regular_file(data / "metadata.csv", root)
        rows = read_metadata(data / "metadata.csv")
        if not rows:
            raise ValueError("metadata为空")
        excluded = {name: row for name, row in rows.items() if row["annotation_status"] == "reviewed_excluded"}
        manifest = {'count':0,'records':[]}
        if excluded or (data/'excluded/manifest.json').exists():
            regular_file(data / "excluded/manifest.json", root)
            manifest = json.loads((data / "excluded/manifest.json").read_text(encoding="utf-8"))
        archive = {}
        for record in manifest["records"]:
            name = filename(record["filename"])
            if name in archive:
                raise ValueError(f"隔离manifest图片名重复：{name}")
            archive[name] = record
        if set(archive) != set(excluded):
            error("隔离manifest与根metadata的reviewed_excluded名单不一致")
        if manifest.get("count") != len(archive):
            error("隔离manifest的count不一致")
        if excluded or (data/'excluded/metadata.csv').exists():
            regular_file(data / "excluded/metadata.csv", root)
            if read_metadata(data / "excluded/metadata.csv") != excluded:
                error("隔离metadata与根metadata中的排除记录不一致")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"status": "fail", "error_count": 1, "errors": [str(exc)]}

    expected = {"active_images": set(), "active_labels": set(), "excluded_images": set(), "excluded_labels": set()}
    counts = {split: Counter(images=0, positive_images=0, negative_images=0, boxes=0) for split in SPLITS}
    excluded_label_issues = 0
    excluded_splits = Counter()
    for name, row in rows.items():
        split, status = row["split"], row["annotation_status"]
        if split not in SPLITS or status not in STATUSES or Path(name).suffix.lower() not in IMAGE_SUFFIXES:
            error(f"metadata的split、状态或图片扩展名非法：{name}")
            continue
        if any(row[key] not in {"0", "1"} for key in SCENES):
            error(f"场景字段不是0或1：{name}")
        if row["scene_review_required"] != "0" or row["label_review_required"] != "0":
            error(f"双项审核尚未完成：{name}")
        is_excluded = status == "reviewed_excluded"
        base = data / "excluded" if is_excluded else data
        image = base / "images" / split / name
        label = base / "labels" / split / (Path(name).stem + ".txt")
        prefix = "excluded" if is_excluded else "active"
        expected[prefix + "_images"].add(image)
        if label in expected[prefix + "_labels"]:
            error(f"多张图片共用同一个label路径：{label}")
        expected[prefix + "_labels"].add(label)
        try:
            regular_file(image, root)
            regular_file(label, root)
            if image.stat().st_size == 0:
                raise ValueError(f"图片文件为空：{image}")
            if is_excluded:
                excluded_splits[split] += 1
                record = archive.get(name)
                if not record or record["split"] != split or record.get("meta") != row:
                    raise ValueError(f"隔离记录与metadata不一致：{name}")
                for kind, path in (("images", image), ("labels", label)):
                    if sha256(path) != record[kind]["sha256"]:
                        raise ValueError(f"隔离文件SHA256变化：{path}")
                try:
                    box_count(label)
                except ValueError:
                    excluded_label_issues += 1
                continue
            boxes = box_count(label)
            if row["No Ball"] != ("0" if boxes else "1") or status != ("reviewed_annotation" if boxes else "negative_confirmed"):
                raise ValueError(f"No Ball、审核状态与最终label不一致：{name}")
            counts[split].update(images=1, positive_images=int(boxes > 0), negative_images=int(boxes == 0), boxes=boxes)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            error(exc)

    for prefix, base in (("active", data), ("excluded", data / "excluded")):
        for kind, suffixes in (("images", IMAGE_SUFFIXES), ("labels", {".txt"})):
            found = set()
            directory = base / kind
            if directory.is_symlink():
                error(f"数据目录不能是软链接：{directory}")
            elif directory.exists():
                for path in directory.rglob("*"):
                    if path.is_symlink():
                        error(f"数据路径不能是软链接：{path}")
                    elif path.is_file() and path.suffix.lower() in suffixes:
                        found.add(path)
            wanted = expected[prefix + "_" + kind]
            missing, extra = wanted - found, found - wanted
            if missing or extra:
                error(f"{prefix}/{kind}路径集合不一致：缺少{len(missing)}，多出{len(extra)}；示例{str(next(iter(missing or extra)))}")
    return {
        "status": "pass" if not error_count else "fail",
        "metadata_rows": len(rows),
        "dataset_root": str(data),
        "active": {split: dict(counts[split]) for split in SPLITS},
        "excluded": {"images": len(excluded), "split_counts": dict(excluded_splits), "labels_with_reference_issues": excluded_label_issues},
        "image_pixels_decoded": False,
        "error_count": error_count,
        "errors": errors,
    }


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-config')
    parser.add_argument('--dataset-version')
    args=parser.parse_args()
    result = verify(config=args.dataset_config,version=args.dataset_version)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
