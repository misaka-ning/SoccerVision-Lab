"""Meaningful guards: frozen splits, nano identity, recipe, immutable inputs and no overwrite."""
import importlib.util
import fcntl
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('e05', HERE/'e05.py')
e05 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e05)


class Guards(unittest.TestCase):
    def test_only_requested_split_selected(self):
        rows = [dict(usage='train', filename='a.png'), dict(usage='test', filename='never-open.png')]
        with patch.dict(e05.COUNTS, {'train':1}):
            self.assertEqual(e05.members(rows, 'train', ['a.png']), rows[:1])

    def test_duplicate_or_changed_members_rejected(self):
        rows = [dict(usage='val', filename='a.png'), dict(usage='val', filename='b.png')]
        with patch.dict(e05.COUNTS, {'val':2}):
            for names in (['a.png','a.png'], ['a.png','c.png'], ['a.png']):
                with self.assertRaises(ValueError):
                    e05.members(rows, 'val', names)

    def test_path_traversal_rejected(self):
        with patch.dict(e05.COUNTS, {'val':1}), self.assertRaises(ValueError):
            e05.members([dict(usage='val', filename='../a.png')], 'val', ['../a.png'])

    def test_model_is_nano_and_single_class(self):
        head = SimpleNamespace(nc=1, reg_max=1, one2one_cv3=True)
        model = SimpleNamespace(yaml=dict(scale='n', end2end=True), model=[head])
        e05.check_nano(model, 1)
        model.yaml['scale'] = 's'
        with self.assertRaises(ValueError): e05.check_nano(model, 1)
        model.yaml['scale'] = 'n'
        head.nc = 80
        with self.assertRaises(ValueError): e05.check_nano(model, 1)

    def test_recipe_preserves_effective_choices(self):
        cfg = e05.recipe(Path('/tmp/e05-test-run'))
        self.assertTrue(cfg['nms'])
        self.assertEqual((cfg['imgsz'],cfg['batch'],cfg['seed']), (640,8,42))
        self.assertEqual((cfg['epochs'],cfg['patience'],cfg['optimizer']), (100,30,'AdamW'))
        self.assertFalse(cfg['exist_ok'])

    def test_integrity_changes_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            protected = run/'input.txt'
            protected.write_text('frozen')
            e05.dump(run/'protected_inputs.json', {str(protected):e05.sha(protected)})
            e05.dump(run/'train_val_expected_hashes.json', {})
            self.assertTrue(e05.verify(run)['unchanged'])
            protected.write_text('changed')
            with self.assertRaises(ValueError): e05.verify(run)

    def test_run_cannot_escape_experiment(self):
        with self.assertRaises(ValueError): e05.run_path('/tmp')

    def test_duplicate_training_refused_before_model_load(self):
        with tempfile.TemporaryDirectory() as temp:
            here = Path(temp)
            with (here/'.training.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(e05, 'HERE', here), self.assertRaisesRegex(ValueError, '另一个 E05'):
                    e05.train(here/'run')

    def test_existing_training_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            here = Path(temp)
            run = here/'run'
            (run/'train').mkdir(parents=True)
            e05.dump(run/'run_record.json', {'status':'prepared'})
            with patch.object(e05, 'HERE', here), patch.object(e05, 'runtime'), patch.object(e05, 'verify', return_value={}):
                with self.assertRaises(FileExistsError): e05.train(run)


if __name__ == '__main__':
    unittest.main()
