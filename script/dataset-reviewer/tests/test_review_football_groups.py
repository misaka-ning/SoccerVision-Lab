#!/usr/bin/env python3
"""Temporary fixtures for immutable review selection and 50-image pages."""
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parents[1] / 'review_football_groups.py'
SPEC = importlib.util.spec_from_file_location('review_football_groups', SCRIPT)
GROUPS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GROUPS)


class ReviewGroupsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.review, self.dataset = base / 'review', base / 'datasets'
        (self.review / 'batches').mkdir(parents=True)
        (self.review / 'batch-001').mkdir()
        self.dataset.mkdir()
        self.names = [f'frame_{i:06d}_{eye}.png'
                      for i in range(501) for eye in ('left', 'right')]
        # Odd priority count also exercises a selected single eye in default mode.
        self.priority = self.names[:209]
        self.passed = self.names[-2:]
        (self.review / 'batches/batch-001.txt').write_text(
            ''.join(n + '\n' for n in self.names), encoding='utf-8')
        (self.review / 'batches/batch-001-priority.txt').write_text(
            ''.join(n + '\n' for n in self.priority), encoding='utf-8')
        (self.review / 'batch-001/proposals.json').write_text(
            json.dumps([{'filename': n} for n in self.names]), encoding='utf-8')
        self.rows = [{
            '图片': n, 'label_review_required': '0' if n in self.passed else '1',
            'scene_review_required': '0' if n in self.passed else '1',
            'source_video': '/fixture/source.avi', 'source_frame_idx': str(i // 2),
        } for i, n in enumerate(self.names)]
        # A partially reviewed row must remain selected.
        self.rows[250]['label_review_required'] = '0'
        self.rows[252]['scene_review_required'] = '0'
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=list(self.rows[0]), lineterminator='\r\n')
        writer.writeheader()
        writer.writerows(self.rows)
        self.metadata = stream.getvalue().encode('utf-8-sig')
        (self.dataset / 'metadata.csv').write_bytes(self.metadata)

    def selection(self):
        out = GROUPS.output_dir(self.review, 1)
        manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
        pages = [GROUPS.read_names(out / g['file']) for g in manifest['groups']]
        return out, manifest, pages, [n for page in pages for n in page]

    def assert_pairs_together(self, pages):
        membership = {name: page for page, names in enumerate(pages) for name in names}
        rows = {r['图片']: r for r in self.rows}
        frames = {}
        for name, page in membership.items():
            frames.setdefault(GROUPS.frame_key(name, rows[name]), set()).add(page)
        self.assertTrue(all(len(pages) == 1 for pages in frames.values()))

    def test_default_retains_non_priority_selection(self):
        GROUPS.create(self.review, self.dataset, 1)
        out, manifest, pages, names = self.selection()
        self.assertEqual(set(names), set(self.names) - set(self.priority) - set(self.passed))
        self.assertEqual(manifest['selection'], 'non_priority_pending')
        self.assertFalse(manifest['include_priority'])
        self.assertEqual(manifest['priority_count'], 209)
        self.assertEqual(manifest['excluded_priority_count'], 209)
        self.assertEqual(manifest['excluded_priority_pending'], 209)
        self.assertEqual(len(names), 791)
        self.assertIn(self.names[250], names)
        self.assertIn(self.names[252], names)
        self.assert_pairs_together(pages)
        self.assertIn('其余图片', (out / 'README.md').read_text(encoding='utf-8'))
        self.assertEqual((self.dataset / 'metadata.csv').read_bytes(), self.metadata)

    def test_include_priority_is_twenty_fixed_pages_and_excludes_passed(self):
        GROUPS.create(self.review, self.dataset, 1, include_priority=True)
        out, manifest, pages, names = self.selection()
        self.assertEqual(set(names), set(self.names) - set(self.passed))
        self.assertEqual([len(page) for page in pages], [50] * 20)
        self.assertEqual(manifest['selection'], 'all_pending')
        self.assertTrue(manifest['include_priority'])
        self.assertEqual(manifest['priority_count'], 209)
        self.assertEqual(manifest['priority_pending_count'], 209)
        self.assertEqual(manifest['excluded_priority_count'], 0)
        self.assertEqual(manifest['excluded_priority_pending'], 0)
        self.assertEqual(manifest['excluded_already_passed'], self.passed)
        self.assert_pairs_together(pages)
        guide = (out / 'README.md').read_text(encoding='utf-8')
        self.assertIn('全部待审图片（含疑点）', guide)
        self.assertNotIn('不混入这些组', guide)
        self.assertEqual(GROUPS.read_names(GROUPS.gallery_list(self.review, self.dataset, 1)), names)
        self.assertEqual(len(GROUPS.progress(self.review, self.dataset, 1)), 20)
        self.assertEqual((self.dataset / 'metadata.csv').read_bytes(), self.metadata)

    def test_existing_group_files_and_manifest_are_never_replaced(self):
        GROUPS.create(self.review, self.dataset, 1)
        out = GROUPS.output_dir(self.review, 1)
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir()}
        with self.assertRaisesRegex(ValueError, '固定分组已存在'):
            GROUPS.create(self.review, self.dataset, 1, include_priority=True)
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir()}
        self.assertEqual(before, after)

    def test_passed_priority_images_stay_excluded(self):
        for row in self.rows[:2]:
            row['label_review_required'] = '0'
            row['scene_review_required'] = '0'
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=list(self.rows[0]))
        writer.writeheader()
        writer.writerows(self.rows)
        (self.dataset / 'metadata.csv').write_bytes(stream.getvalue().encode('utf-8-sig'))
        GROUPS.create(self.review, self.dataset, 1, include_priority=True)
        _, manifest, pages, names = self.selection()
        self.assertFalse(set(self.names[:2]) & set(names))
        self.assertEqual(manifest['priority_count'], 209)
        self.assertEqual(manifest['priority_pending_count'], 207)
        self.assertEqual(manifest['excluded_priority_count'], 0)
        self.assertEqual(set(manifest['excluded_already_passed']), set(self.names[:2] + self.passed))
        self.assert_pairs_together(pages)

    def test_flag_is_rejected_for_read_commands(self):
        for command in ('status', 'next', 'gallery-list'):
            with self.subTest(command=command):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), command, '--batch', '1', '--include-priority'],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn('--include-priority 仅可用于 create', result.stderr)


if __name__ == '__main__':
    unittest.main()
