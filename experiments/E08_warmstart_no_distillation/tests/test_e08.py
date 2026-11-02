"""Portable acceptance tests: no historical runs, Test data or GPU required."""
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('control_e08', HERE/'e08.py')
e = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = e
spec.loader.exec_module(e)
import compare


class Configuration(unittest.TestCase):
    def test_exact_single_semantic_difference(self):
        run = Path('/tmp/pair')
        kd, plain = e.config_for(run, True), e.config_for(run)
        self.assertEqual(set(e.control.assert_pair(kd, plain)), {'distill_model'})
        self.assertEqual(plain['dis'], 6.)
        self.assertEqual([plain[k] for k in ('batch', 'imgsz', 'seed', 'epochs', 'patience')], [8, 640, 42, 100, 30])
        self.assertIsNone(plain['distill_model'])
        self.assertEqual(e.STUDENT_SHA, e.reference.STUDENT_INIT_SHA)
        # Exercise the actual E07 recipe function, replacing only absent E01 file IO.
        with patch.object(e.base, 'recipe', return_value={k: v for k, v in plain.items() if k not in ('distill_model', 'dis')}):
            self.assertEqual(e.reference.training_config(run), kd)

    def test_recipe_drift_and_dis_zero_only_rejected(self):
        kd, plain = e.config_for(Path('/tmp/a'), True), e.config_for(Path('/tmp/b'))
        for key, value in [('lr0', .0001), ('batch', 4), ('patience', 10), ('seed', 43),
                           ('hsv_s', .1), ('dis', 0), ('resume', True)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                e.control.assert_pair(kd, {**plain, key: value})
        with self.assertRaises(ValueError):
            e.control.assert_no_kd({**kd, 'dis': 0})

    def test_dry_run_does_not_import_runtime_or_read_weights(self):
        with patch.object(e, 'runtime', side_effect=AssertionError('runtime loaded')), \
                patch.object(e, 'sha', side_effect=AssertionError('weight read')):
            result = e.dry_run()
        self.assertFalse(result['training_started'])
        self.assertIn('not_run', result['frozen_inputs'])

    def test_teacher_guard_intercepts_native_loader_and_constructor(self):
        from ultralytics.nn import tasks
        from ultralytics.nn.distill_model import DistillationModel
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            with e.control.no_teacher_load([], run) as evidence:
                with self.assertRaisesRegex(ValueError, 'teacher forbidden'):
                    tasks.torch_safe_load('/missing/E01_teacher.pt')
                with self.assertRaisesRegex(ValueError, 'construction is forbidden'):
                    DistillationModel(None, '/missing/E01_teacher.pt')
            self.assertEqual(evidence['teacher_loads'], 0)
            self.assertEqual(evidence['checkpoint_loads'], [])
            self.assertEqual(evidence['teacher_construction_attempts'], 1)

    def test_lock_is_shared_with_e07(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old, warm, plain = [root/n for n in ('E05', 'E07', 'E08')]
            for p in (old, warm, plain): p.mkdir()
            with patch.object(e.reference, 'E05', old), patch.object(e.reference, 'HERE', warm), patch.object(e, 'HERE', plain):
                with e.reference.gpu_lock(), self.assertRaises(ValueError):
                    with e.gpu_lock(): pass
                with e.gpu_lock(), self.assertRaises(ValueError):
                    with e.reference.gpu_lock(): pass

    def test_run_isolation_and_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = root/'runs/one'; run.mkdir(parents=True)
            payload = root/'data/images/train/one.png'; payload.parent.mkdir(parents=True); payload.write_bytes(b'one')
            e.dump(run/'run_record.json', dict(experiment_id='E08', data_root=str(root/'data')))
            e.dump(run/'protected_inputs.json', {})
            e.dump(run/'train_val_expected_hashes.json', {str(payload): e.sha(payload)})
            with patch.object(e, 'HERE', root):
                self.assertEqual(e.run_path(str(run)), run)
                with self.assertRaises((ValueError, FileNotFoundError)): e.run_path(str(root))
            for split in ('train', 'val'):
                for kind in ('images', 'labels'):
                    (run/'runtime/dataset'/kind/split).mkdir(parents=True)
                    (root/'data'/kind/split).mkdir(parents=True, exist_ok=True)
            (run/'runtime/dataset/images/train/one.png').symlink_to(payload)
            self.assertTrue(e.verify(run)['unchanged'])
            link = run/'runtime/dataset/images/train/one.png'
            link.unlink(); link.symlink_to(root/'data/images/test/forbidden.png')
            with self.assertRaisesRegex(ValueError, 'runtime view target'):
                e.verify(run)
            link.unlink(); link.symlink_to(payload)
            payload.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'changed'): e.verify(run)
            forbidden = root/'data/images/test/unopened.png'
            e.dump(run/'train_val_expected_hashes.json', {str(forbidden): 'invalid'})
            with patch.object(e, 'sha', side_effect=AssertionError('must reject before open')), self.assertRaisesRegex(ValueError, 'Train/Val'):
                e.verify(run)

    def test_effective_defaults_drift_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp); (run/'reference').mkdir()
            from ultralytics.cfg import get_cfg
            kd = vars(get_cfg(overrides=e.config_for(run, True)))
            plain = vars(get_cfg(overrides=e.config_for(run)))
            e.dump(run/'reference/train.effective.json', kd)
            self.assertEqual(set(e.effective_pair(run, plain)), {'distill_model'})
            plain['momentum'] += .01
            with self.assertRaises(ValueError): e.effective_pair(run, plain)

    def test_zero_area_revision_preserves_shared_source(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            source = e.ROOT/'script/model-evaluation/evaluate.py'
            before = e.sha(source)
            revision = e.evaluation_revision(run)
            self.assertEqual(e.sha(source), before)
            self.assertIn('np.any(xyxy[:,2:]<xyxy[:,:2])', (run/'evaluation_code/evaluate.py').read_text())
            self.assertEqual(e.sha(run/'evaluation_code/eval_metrics.py'), revision['original_sha256']['eval_metrics.py'])


class BudgetAndComparison(unittest.TestCase):
    def test_csv_counts_not_progress_callback_and_missing_not_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp); (run/'train').mkdir()
            e.dump(run/'progress.json', dict(epoch=74))
            (run/'train/results.csv').write_text('epoch,metrics/mAP50-95(B)\n'+''.join(
                f'{i},{.8 if i == 43 else .7}\n' for i in range(1, 74)))
            result = e.control.csv_budget(run, dict(status='trained', training=dict(elapsed_seconds=2365.742)))
            self.assertEqual((result['epochs_completed'], result['best_csv_map_epoch'], result['stop_reason']), (73, 43, 'early_stopping'))
            self.assertEqual(result['optimizer_updates'], 'not_run')
            resumed = dict(status='trained', training=dict(elapsed_seconds=10, resume_events=[{}]))
            self.assertEqual(e.control.csv_budget(run, resumed)['elapsed_seconds'], 'not_run')
            self.assertEqual(e.control.csv_budget(run, dict(status='prepared'))['status'], 'not_run')

    def test_missing_and_partial_comparison_do_not_invent_metrics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(e, 'HERE', root), patch.object(e.reference, 'PARENT', root/'E05'), \
                    patch.object(e, 'E07_RUN', root/'E07'):
                first = compare.compare(e)
                second = compare.compare(e)
            self.assertNotEqual(first, second)
            summary = e.load(first/'comparison.json')
            for row in summary['models'].values():
                self.assertEqual(row['status'], 'not_run')
                self.assertTrue(all(v == 'not_run' for v in row['metrics'].values()))
            self.assertEqual(summary['budget_delta']['epochs_completed'], 'not_run')
            self.assertIn('Precision', (first/'COMPARISON.md').read_text())

    def test_checkpoint_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp); path = run/'train/weights/best.pt'; path.parent.mkdir(parents=True); path.write_bytes(b'original')
            e.dump(run/'run_record.json', dict(status='trained', training=dict(checkpoints=dict(best=dict(sha256=e.sha(path))))))
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'mismatch'): compare.available_checkpoint(e, run)

    def test_zero_area_is_retained_as_fp_and_fpr_is_image_based(self):
        metrics = e.base.module('e08_metric_test', e.ROOT/'script/model-evaluation/eval_metrics.py')
        rows = metrics.prepare([dict(image='positive', gt=[[0, 0, 10, 10]], boxes=[[0, 0, 10, 10]], scores=[.9],
                   flags={'Small': 1, 'Occluded': 1, 'Blurred': 0, 'No Ball': 0}),
               dict(image='negative', gt=[], boxes=[[0, 1, 10, 1], [0, 0, 2, 2]], scores=[.8, .7],
                   flags={'Small': 0, 'Occluded': 0, 'Blurred': 0, 'No Ball': 1})])
        m = metrics.operating(rows, .45, .5)
        self.assertEqual((m['TP'], m['FP'], m['no_ball_false_positive_images'], m['no_ball_images']), (1, 2, 1, 1))
        self.assertEqual(m['precision'], 1/3)
        self.assertEqual(m['no_ball_false_positive_rate'], 1)
        self.assertEqual(metrics.operating(metrics.groups(rows)['Small'], .45, .5)['recall'], 1)


if __name__ == '__main__': unittest.main()
