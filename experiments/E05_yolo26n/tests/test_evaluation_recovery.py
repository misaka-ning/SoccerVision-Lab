"""Regression checks for the real metrics.json API, safe reuse, and source repair audit."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('e05_recovery', HERE/'e05.py')
e05 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e05)


class Recovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root/'data'
        self.run = self.root/'runs/test'
        self.output = self.run/'val_0p45_recovery'
        for directory in (self.data/'images/val', self.data/'labels/val', self.root/'script/model-evaluation', self.output):
            directory.mkdir(parents=True)
        (self.root/'script/model-evaluation/evaluate.py').write_text('# frozen shared evaluator')
        self.image = self.data/'images/val/left.png'
        self.label = self.data/'labels/val/left.txt'
        self.image.write_bytes(b'fixture image bytes')
        self.label.write_text('')
        (self.data/'metadata.csv').write_text('fixture metadata')
        (self.run/'dataset.val-evaluation.yaml').write_text('fixture dataset')
        self.baseline = self.root/'baseline.pt'
        self.best = self.run/'train/weights/best.pt'
        self.best.parent.mkdir(parents=True)
        self.baseline.write_bytes(b'baseline')
        self.best.write_bytes(b'nano')
        e05.dump(self.run/'train_val_expected_hashes.json', {str(p):e05.sha(p) for p in (self.image,self.label)})
        e05.dump(self.run/'run_record.json', dict(status='trained', training=dict(checkpoints=dict(best=dict(sha256=e05.sha(self.best))))))
        self.patches = [patch.object(e05,'ROOT',self.root), patch.object(e05,'DATA',self.data),
                        patch.object(e05,'BASELINE',self.baseline), patch.dict(e05.COUNTS, {'val':1})]
        for p in self.patches: p.start()
        self.directory = self.output/'E01_s'
        self.write_result(self.directory, self.baseline)

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.temp.cleanup()

    def write_result(self, directory, checkpoint):
        directory.mkdir(exist_ok=False)
        options = dict(e05.evaluation_options(self.run,checkpoint,'0',.45),limit=None)
        result = dict(status='complete',model=str(checkpoint),split='val',partial_split=False,
            available_before_limit=1,skipped_images=0,model_class_id=0,input_files_verified_unchanged=True,
            metrics=dict(images=1,mAP50=.9,mAP50_95=.8,precision=.9,recall=.8,no_ball_false_positive_rate=0),
            arguments=options,runtime=dict(backend_end2end=False,backend_fp16=False,actual_input_shape=[640,640]))
        selected = [dict(image=str(self.image),label=str(self.label),image_sha256=e05.sha(self.image),label_sha256=e05.sha(self.label))]
        e05.dump(directory/'status.json',dict(status='complete',input_files_verified_unchanged=True))
        e05.dump(directory/'metrics.json',result)
        e05.dump(directory/'inputs_manifest.json',dict(arguments=options,model_sha256=e05.sha(checkpoint),
            dataset_yaml_sha256=e05.sha(self.run/'dataset.val-evaluation.yaml'),metadata_sha256=e05.sha(self.data/'metadata.csv'),
            evaluation_code_sha256={p.name:e05.sha(p) for p in (self.root/'script/model-evaluation').glob('*.py')},selected=selected))
        (directory/'predictions.jsonl').write_text(json.dumps(dict(image=str(self.image)))+'\n')

    def read_result(self):
        return e05.completed_evaluation(self.directory,self.run,self.baseline,'0',.45)

    def test_reads_actual_metrics_contract_without_summary_json(self):
        self.assertFalse((self.directory/'summary.json').exists())
        self.assertEqual(self.read_result()['metrics']['mAP50_95'], .8)

    def test_rejects_different_threshold(self):
        with self.assertRaises(ValueError):
            e05.completed_evaluation(self.directory,self.run,self.baseline,'0',.25)

    def test_rejects_changed_model(self):
        self.baseline.write_bytes(b'changed')
        with self.assertRaises(ValueError): self.read_result()

    def test_rejects_partial_or_failed_output(self):
        status = self.directory/'status.json'
        e05.dump(status,dict(status='failed'))
        with self.assertRaises(ValueError): self.read_result()
        e05.dump(status,dict(status='complete',input_files_verified_unchanged=True))
        metrics = e05.load(self.directory/'metrics.json')
        metrics['partial_split'] = True
        e05.dump(self.directory/'metrics.json',metrics)
        with self.assertRaises(ValueError): self.read_result()

    def test_rejects_missing_prediction(self):
        (self.directory/'predictions.jsonl').write_text('')
        with self.assertRaises(ValueError): self.read_result()

    def test_rejects_changed_evaluation_code(self):
        (self.root/'script/model-evaluation/evaluate.py').write_text('# changed')
        with self.assertRaises(ValueError): self.read_result()

    def test_dry_run_reuses_baseline_without_starting_prediction(self):
        with patch.object(e05,'runtime'), patch.object(e05,'verify',return_value={}), patch.object(e05.subprocess,'run') as run:
            e05.evaluate(self.run,'0',.45,str(self.output),dry_run=True)
            run.assert_not_called()
        self.assertFalse((self.output/'E05_n').exists())

    def test_continuation_runs_only_nano_and_finishes_comparison(self):
        before = {p:e05.sha(p) for p in self.directory.iterdir()}
        def predict(command, check):
            self.assertTrue(check)
            self.assertEqual(command[command.index('--model')+1],str(self.best))
            self.write_result(Path(command[command.index('--output')+1]),self.best)
        with patch.object(e05,'runtime'), patch.object(e05,'verify',return_value={}), patch.object(e05.subprocess,'run',side_effect=predict) as run:
            e05.evaluate(self.run,'0',.45,str(self.output))
            self.assertEqual(run.call_count,1)
        self.assertTrue((self.output/'COMPARISON.md').is_file())
        self.assertEqual({p:e05.sha(p) for p in self.directory.iterdir()},before)


class SourceRepair(unittest.TestCase):
    def test_only_archived_post_training_orchestration_repair_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            here = root/'experiments/E05'
            here.mkdir(parents=True)
            run = here/'runs/one'
            snapshot = run/'source/experiments/E05/e05.py'
            snapshot.parent.mkdir(parents=True)
            snapshot.write_text('original source')
            source = here/'e05.py'
            source.write_text('repaired source')
            data = root/'data.txt'
            data.write_text('immutable')
            original = e05.sha(snapshot)
            e05.dump(run/'protected_inputs.json',{str(source):original})
            e05.dump(run/'train_val_expected_hashes.json',{str(data):e05.sha(data)})
            e05.dump(run/'run_record.json',dict(status='trained'))
            revision = run/'post_training_revisions/repair'
            revision.mkdir(parents=True)
            (revision/'e05.revised.py').write_bytes(source.read_bytes())
            (revision/'source.diff').write_text('reviewed patch')
            with patch.object(e05,'HERE',here), patch.object(e05,'ROOT',root):
                with self.assertRaises(ValueError): e05.verify(run)
                e05.dump(revision/'manifest.json',dict(run_id=run.name,source=str(source),original_sha256=original,
                    revised_sha256=e05.sha(source),protected_inputs_sha256=e05.sha(run/'protected_inputs.json'),patch_sha256=e05.sha(revision/'source.diff')))
                result = e05.verify(run)
                self.assertFalse(result['unchanged'])
                self.assertTrue(result['data_and_model_files_unchanged'])
                self.assertEqual(result['post_training_source_revisions'],[str(revision/'manifest.json')])
                e05.dump(run/'run_record.json',dict(status='training'))
                with self.assertRaises(ValueError): e05.verify(run)
                e05.dump(run/'run_record.json',dict(status='trained'))
                data.write_text('changed data')
                with self.assertRaises(ValueError): e05.verify(run)


if __name__ == '__main__':
    unittest.main()
