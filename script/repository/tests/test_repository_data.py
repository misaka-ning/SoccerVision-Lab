"""Substantive checks for relocation, data consistency and preflight safety."""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import prepare_data
import verify_dataset

FIELDS = ["图片", "Small", "Occluded", "Blurred", "No Ball", "split", "annotation_status", "scene_review_required", "label_review_required"]


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class RepositoryDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "moved clone"
        self.data = self.root / "datasets/v0"
        self.version = self.root / "datasets/v1"
        for kind in ('images','labels'):
            for split in prepare_data.SPLITS:
                (self.data/kind/split).mkdir(parents=True,exist_ok=True)
        self.rows, self.records = [], []
        write_file(self.root / 'script/config.yaml', b'dataset_version: v0\ndatasets:\n  v0:\n    root: datasets/v0\n  v1:\n    root: datasets/v1\n    source_version: v0\n    manifest_id: football_holdout_20261019_v1\n')
        for index, usage in enumerate(prepare_data.USAGES):
            name = f"sample_{index}.png"
            split = "val" if usage == "val" else "train"
            positive = usage == "train"
            row = dict(zip(FIELDS, [name, "0", "0", "0", "0" if positive else "1", split, "reviewed_annotation" if positive else "negative_confirmed", "0", "0"]))
            self.rows.append(row)
            image = self.data / "images" / split / name
            label = self.data / "labels" / split / (Path(name).stem + ".txt")
            write_file(image, b"nonempty image bytes " + str(index).encode())
            write_file(label, b"0 0.5 0.5 0.2 0.2\n" if positive else b"")
            self.records.append({"filename": name, "original_image": "/old/computer/datasets/images/" + split + "/" + name,
                                 "original_label": "/old/computer/datasets/labels/" + split + "/" + label.name,
                                 "original_split": split, "usage": usage, "annotation_status": row["annotation_status"],
                                 "image_sha256": verify_dataset.sha256(image), "label_sha256": verify_dataset.sha256(label),
                                 **{key: int(row[key]) for key in verify_dataset.SCENES}})
        excluded = dict(zip(FIELDS, ["excluded.png", "0", "0", "0", "1", "test", "reviewed_excluded", "0", "0"]))
        self.rows.append(excluded)
        image = self.data / "excluded/images/test/excluded.png"
        label = self.data / "excluded/labels/test/excluded.txt"
        write_file(image, b"excluded reference")
        write_file(label, b"0 0.99 0.5 0.5 0.2\n")
        manifest = {"count": 1, "records": [{"filename": "excluded.png", "split": "test", "meta": excluded,
                                              "images": {"sha256": verify_dataset.sha256(image)}, "labels": {"sha256": verify_dataset.sha256(label)}}]}
        write_file(self.data / "excluded/manifest.json", json.dumps(manifest).encode())
        write_csv(self.data / "excluded/metadata.csv", [excluded])
        write_csv(self.data / "metadata.csv", self.rows)
        write_file(self.data / "dataset.yaml", b"# frozen config at old location\n")
        write_csv(self.version / "metadata.csv", [dict(row, split=record["usage"]) for row, record in zip(self.rows, self.records) if record["usage"] in prepare_data.SPLITS])
        self.save_manifest()
        write_file(self.version / "lists/train.txt", b"/old/computer/frozen-list.png\n")
        write_file(self.version / "dataset.yaml", b"# frozen holdout config\n")

    def save_manifest(self):
        write_file(self.version / "manifest.json", json.dumps({"version_id": "football_holdout_20261019_v1", "records": self.records}).encode())

    def target(self, record, kind="images"):
        base = self.version if record["usage"] in prepare_data.SPLITS else self.version / "reserved"
        name = record["filename"] if kind == "images" else Path(record["filename"]).stem + ".txt"
        return base / kind / record["usage"] / name

    def test_current_consistency_and_excluded_reference_boundary(self):
        result = verify_dataset.verify(self.root)
        self.assertEqual(result["status"], "pass", result)
        self.assertEqual(result["active"]["train"]["images"], 4)
        self.assertEqual(result["excluded"]["labels_with_reference_issues"], 1)
        self.assertEqual(result["active"]["test"]["images"], 0)
        label = self.data / "labels/train/sample_0.txt"
        label.write_text("0 0.99 0.5 0.5 0.2\n")
        self.assertEqual(verify_dataset.verify(self.root)["status"], "fail")

    def test_no_ball_conflict_and_orphan_are_rejected(self):
        self.rows[0]["No Ball"] = "1"
        write_csv(self.data / "metadata.csv", self.rows)
        self.assertEqual(verify_dataset.verify(self.root)["status"], "fail")
        self.rows[0]["No Ball"] = "0"
        write_csv(self.data / "metadata.csv", self.rows)
        write_file(self.data / "labels/train/orphan.txt", b"")
        result = verify_dataset.verify(self.root)
        self.assertEqual(result["status"], "fail")
        self.assertTrue(any("多出1" in error for error in result["errors"]))

    def test_check_only_does_not_create_any_files(self):
        before = {p.relative_to(self.root) for p in self.root.rglob("*")}
        result = prepare_data.prepare("holdout", True, self.root, version="v1")
        self.assertEqual(result["status"], "missing_copies")
        self.assertEqual(result["missing_files"], 10)
        self.assertEqual(before, {p.relative_to(self.root) for p in self.root.rglob("*")})

    def test_relocation_materializes_independent_copies_and_keeps_evidence(self):
        frozen = [self.data / "metadata.csv", self.data / "dataset.yaml", self.version / "manifest.json", self.version / "dataset.yaml", self.version / "lists/train.txt"]
        hashes = {p: verify_dataset.sha256(p) for p in frozen}
        result = prepare_data.prepare("holdout", False, self.root, version="v1")
        self.assertEqual(result["copied_files"], 10)
        output = self.root / "experiments/configs/datasets/v1"
        yaml = (output / "dataset.yaml").read_text()
        self.assertIn(json.dumps(str(self.version)), yaml)
        self.assertNotIn("/old/computer", yaml)
        for record in self.records:
            image = self.target(record)
            self.assertEqual((output / (record["usage"] + ".txt")).read_text(), str(image) + "\n")
            source = self.data / "images" / record["original_split"] / record["filename"]
            self.assertFalse(os.path.samestat(source.stat(), image.stat()))
            self.assertEqual(verify_dataset.sha256(image), record["image_sha256"])
        self.assertEqual(hashes, {p: verify_dataset.sha256(p) for p in frozen})
        self.assertEqual(prepare_data.prepare("holdout", False, self.root, version="v1")["copied_files"], 0)

    def test_late_source_mismatch_prevents_all_copying(self):
        record = self.records[-1]
        (self.data / "images" / record["original_split"] / record["filename"]).write_bytes(b"changed source")
        with self.assertRaisesRegex(ValueError, "canonical源文件SHA256"):
            prepare_data.prepare("holdout", False, self.root, version="v1")
        self.assertFalse(self.target(self.records[0]).exists())
        self.assertFalse((self.root / "experiments").exists())

    def test_late_destination_conflict_is_never_overwritten(self):
        target = self.target(self.records[-1])
        write_file(target, b"existing human change")
        with self.assertRaisesRegex(ValueError, "拒绝覆盖"):
            prepare_data.prepare("holdout", False, self.root, version="v1")
        self.assertEqual(target.read_bytes(), b"existing human change")
        self.assertFalse(self.target(self.records[0]).exists())
        self.assertFalse((self.root / "experiments").exists())

    def test_existing_hardlink_or_symlink_is_rejected(self):
        record = self.records[0]
        source = self.data / "images" / record["original_split"] / record["filename"]
        target = self.target(record)
        target.parent.mkdir(parents=True)
        os.link(source, target)
        with self.assertRaisesRegex(ValueError, "inode"):
            prepare_data.prepare("holdout", True, self.root, version="v1")
        target.unlink()
        target.symlink_to(source)
        with self.assertRaisesRegex(ValueError, "软链接"):
            prepare_data.prepare("holdout", True, self.root, version="v1")

    def test_cli_finds_clone_root_from_another_working_directory(self):
        scripts = self.root / "script/repository"
        scripts.mkdir(parents=True,exist_ok=True)
        (scripts.parent / 'common').mkdir()
        for helper in ('__init__.py','dataset_config.py'):
            shutil.copyfile(SCRIPTS.parent / 'common' / helper, scripts.parent / 'common' / helper)
        for name in ("prepare_data.py", "verify_dataset.py"):
            shutil.copyfile(SCRIPTS / name, scripts / name)
        result = subprocess.run([sys.executable, "-B", str(scripts / "prepare_data.py")], cwd=self.temp.name, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        output = self.root / "experiments/configs/datasets/v0.dataset.yaml"
        self.assertEqual(json.loads(result.stdout)["dataset_yaml"], str(output))
        self.assertIn(json.dumps(str(self.data)), output.read_text())
        checked = subprocess.run([sys.executable, "-B", str(scripts / "verify_dataset.py")], cwd=self.temp.name, capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)


if __name__ == "__main__":
    unittest.main()
