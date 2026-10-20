#!/usr/bin/env python3
"""Prepare clone-local YOLO entry points without rewriting frozen evidence."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from verify_dataset import ROOT, SCENES, SPLITS, filename, read_metadata, regular_file, sha256, verify
from common.dataset_config import load_dataset,materialize_yaml

USAGES = (*SPLITS, "buffer", "heldout_unused")


def safe_output(path: Path, root: Path) -> None:
    path.relative_to(root)
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f"输出路径不能是软链接：{part}")
        if part == root:
            break
        if part.exists() and part != path and not part.is_dir():
            raise ValueError(f"输出父路径不是目录：{part}")
    if path.exists() and not path.is_file():
        raise ValueError(f"输出位置不是普通文件：{path}")


def write_local(path: Path, content: str, root: Path) -> None:
    safe_output(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def yaml_config(root: Path, entries: dict[str, Path | str]) -> str:
    lines = ["# Generated locally; frozen dataset configuration remains unchanged.", "path: " + json.dumps(str(root), ensure_ascii=False)]
    lines.extend(key + ": " + json.dumps(str(value), ensure_ascii=False) for key, value in entries.items())
    return "\n".join([*lines, "nc: 1", "names:", "  0: football", ""])


def prepare(view: str = "current", check_only: bool = False, root: Path = ROOT, *, config=None, version=None) -> dict:
    selected=load_dataset(config,version,root=root)
    if view == 'holdout':
        if not selected['source_version'] or not selected['manifest_id']:
            raise ValueError('所选版本未配置source_version/manifest_id；请选择配置中的留出版本。')
        source=load_dataset(selected['config'],selected['source_version'],root=root)['root']
    else:
        source=selected['root']
    canonical = verify(root,data=source)
    if canonical["status"] != "pass":
        raise ValueError("canonical数据校验失败：" + json.dumps(canonical, ensure_ascii=False))
    if view == "current":
        output = root / 'experiments/configs/datasets' / f'{selected["version"]}.dataset.yaml'
        safe_output(output, root)
        if not check_only:
            output=materialize_yaml(selected)
        return {"status": "pass", "view": view, "dataset_version":selected['version'], "dataset_root":str(source), "check_only": check_only, "dataset_yaml": str(output), "active": canonical["active"]}

    version = selected['root']
    manifest_path = version / "manifest.json"
    regular_file(manifest_path, root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version_id") != selected['manifest_id'] or not isinstance(manifest.get("records"), list):
        raise ValueError("holdout manifest版本或records无效")
    rows = read_metadata(source / "metadata.csv")
    active = {n: r for n, r in rows.items() if r["annotation_status"] != "reviewed_excluded"}
    seen, destinations = set(), set()
    plans, lists, counts = [], {u: [] for u in USAGES}, Counter()
    # Complete this preflight before creating directories, copies, or configs.
    for record in manifest["records"]:
        name = filename(record["filename"])
        usage, original_split = record["usage"], record["original_split"]
        if name in seen or usage not in USAGES or original_split not in SPLITS:
            raise ValueError(f"holdout重复图片或非法分配：{name}")
        seen.add(name)
        row = active.get(name)
        if not row or row["split"] != original_split:
            raise ValueError(f"holdout源图片不属于指定canonical可用集合：{name}")
        if record["annotation_status"] != row["annotation_status"] or any(str(record[key]) != row[key] for key in SCENES):
            raise ValueError(f"holdout冻结审核字段与canonical不一致：{name}")
        if Path(record["original_image"]).name != name or Path(record["original_label"]).name != Path(name).stem + ".txt":
            raise ValueError(f"holdout原始路径的文件名不一致：{name}")
        base = version if usage in SPLITS else version / "reserved"
        image = base / "images" / usage / name
        lists[usage].append(image)
        counts[usage] += 1
        for kind, target, digest_key in (("images", image, "image_sha256"), ("labels", base / "labels" / usage / (Path(name).stem + ".txt"), "label_sha256")):
            expected = record[digest_key]
            if not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected):
                raise ValueError(f"holdout SHA256格式错误：{name}")
            source_file = source / kind / original_split / target.name
            regular_file(source_file, root)
            if sha256(source_file) != expected:
                raise ValueError(f"canonical源文件SHA256与冻结manifest不一致：{source_file}")
            if target in destinations:
                raise ValueError(f"holdout目标路径重复：{target}")
            destinations.add(target)
            safe_output(target, root)
            exists = target.exists()
            if exists:
                regular_file(target, root)
                if sha256(target) != expected:
                    raise ValueError(f"现有副本SHA256不一致，拒绝覆盖：{target}")
                if os.path.samestat(source_file.stat(), target.stat()):
                    raise ValueError(f"holdout副本不能与canonical共用inode：{target}")
            plans.append((source_file, target, expected, exists))
    if seen != set(active):
        raise ValueError("holdout manifest与canonical可用图片名单不一致")
    formal = read_metadata(version / "metadata.csv")
    expected_formal = {name: dict(active[name], split=record["usage"]) for record in manifest["records"] if record["usage"] in SPLITS for name in [record["filename"]]}
    if formal != expected_formal:
        raise ValueError("holdout metadata与冻结分配/canonical审核字段不一致")
    output = root / 'experiments/configs/datasets' / selected['version']
    outputs = [output / (usage + ".txt") for usage in USAGES] + [output / "dataset.yaml"]
    for path in outputs:
        safe_output(path, root)
    missing = sum(not exists for _, _, _, exists in plans)
    result = {"status": "missing_copies" if check_only and missing else "pass", "view": view, "dataset_version":selected['version'], "check_only": check_only, "counts": dict(counts), "source_files_checked": len(plans), "existing_copies_checked": len(plans) - missing, "missing_files": missing, "copied_files": 0, "dataset_yaml": str(output / "dataset.yaml"), "evaluation_kind": "same_session_segment_holdout"}
    if check_only:
        return result

    for source, target, expected, exists in plans:
        if exists:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            # Exclusive creation also refuses a file appearing after preflight.
            with source.open("rb") as src, target.open("xb") as dst:
                created = True
                shutil.copyfileobj(src, dst, 1024 * 1024)
            if sha256(target) != expected:
                raise ValueError(f"复制期间源内容发生变化：{source}")
            result["copied_files"] += 1
        except BaseException:
            if created:
                target.unlink(missing_ok=True)
            raise
    for usage, images in lists.items():
        write_local(output / (usage + ".txt"), "".join(str(image) + "\n" for image in images), root)
    write_local(output / "dataset.yaml", yaml_config(version, {s: output / (s + ".txt") for s in SPLITS}), root)
    result["missing_files"] = 0
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", choices=("current", "holdout"), default="current")
    parser.add_argument("--check-only", action="store_true", help="仅全量预检，不写配置或补齐副本；缺副本退出1")
    parser.add_argument('--dataset-config')
    parser.add_argument('--dataset-version')
    args = parser.parse_args()
    try:
        result = prepare(args.view, args.check_only,config=args.dataset_config,version=args.dataset_version)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {"status": "fail", "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
