"""Metric semantics tested without Torch, Ultralytics, images or weights."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from synthetic_demo import demo, synthetic_records
from eval_metrics import operating


class SyntheticDemoTests(unittest.TestCase):
    def test_duplicate_is_fp_and_threshold_is_applied_before_rematching(self):
        duplicate = synthetic_records()[:1]
        self.assertEqual(tuple(operating(duplicate, .25, .5)[k]
                               for k in ('TP', 'FP', 'FN')), (1, 1, 0))
        # Higher-IoU .4 box was matched by prepare; after filtering it out,
        # the .9 box must be rematched rather than retaining its old FP label.
        self.assertEqual(duplicate[0]['correct'][:, 0].tolist(), [True, False])
        self.assertEqual(tuple(operating(duplicate, .5, .5)[k]
                               for k in ('TP', 'FP', 'FN')), (1, 0, 0))

    def test_working_points_and_no_ball_denominators(self):
        points = demo()['operating_points']
        for row, counts, precision, recall, fpr, boxes in zip(
                points, [(2, 3, 0), (1, 1, 1), (1, 0, 1)],
                [.4, .5, 1.], [1., .5, .5], [.5, .5, 0.], [2, 1, 0]):
            with self.subTest(confidence=row['confidence']):
                self.assertEqual(tuple(row[k] for k in ('TP', 'FP', 'FN')), counts)
                self.assertAlmostEqual(row['precision'], precision)
                self.assertAlmostEqual(row['recall'], recall)
                self.assertEqual(row['no_ball_images'], 2)
                self.assertEqual(row['no_ball_false_positive_rate'], fpr)
                self.assertEqual(row['no_ball_false_positive_images'], int(fpr * 2))
                self.assertEqual(row['no_ball_false_positive_boxes'], boxes)
                self.assertEqual(row['no_ball_fp_boxes_per_image'], boxes / 2)

    def test_undefined_denominators_remain_none(self):
        rows = synthetic_records()
        self.assertIsNone(operating(rows[:1], .5, .5)['no_ball_false_positive_rate'])
        self.assertIsNone(operating(rows[-1:], .5, .5)['recall'])

    def test_cli_labels_output_and_never_imports_model_stack(self):
        script = Path(__file__).resolve().parents[1] / 'synthetic_demo.py'
        # Reject imports even if the host happens to have these packages.
        code = '''import sys, runpy
class BlockModelStack:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'ultralytics', 'PIL'}:
            raise AssertionError('unexpected model/image dependency: ' + fullname)
sys.meta_path.insert(0, BlockModelStack())
sys.path.insert(0, sys.argv[1])
runpy.run_path(sys.argv[2], run_name='__main__')
'''
        result = subprocess.run([sys.executable, '-B', '-c', code, str(script.parent), str(script)],
                                text=True, capture_output=True, check=True)
        output = json.loads(result.stdout)
        self.assertIn('合成演示', output['label'])
        self.assertIn('非模型成绩', output['label'])
        self.assertEqual(len(output['operating_points']), 3)
        self.assertFalse(any('ap' in key.lower() for row in output['operating_points'] for key in row))


if __name__ == '__main__':
    unittest.main()
