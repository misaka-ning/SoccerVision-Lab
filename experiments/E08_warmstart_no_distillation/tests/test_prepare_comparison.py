"""End-to-end fixture checks for frozen preparation and complete evidence reuse."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('e08_fixture_tests', HERE/'e08.py')
e = importlib.util.module_from_spec(spec); sys.modules[spec.name] = e; spec.loader.exec_module(e)
import compare


class Preparation(unittest.TestCase):
    def test_prepare_relocates_train_val_and_preserves_history(self):
        from PIL import Image
        import yaml
        from ultralytics.cfg import get_cfg
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); data = root/'datasets/v1'; ref = root/'E07/reference'; parent = root/'E05/parent'
            ref.mkdir(parents=True); (parent/'train/weights').mkdir(parents=True)
            initial = parent/'train/weights/best.pt'; initial.write_bytes(b'fixture only, not model weights')
            digest = e.sha(initial); (ref/'init.pt').write_bytes(initial.read_bytes())
            e.dump(parent/'run_record.json', dict(status='trained', training=dict(checkpoints=dict(best=dict(sha256=digest)))))
            e.dump(ref/'run_record.json', dict(experiment_id='E07', status='trained',
                student_initialization=dict(sha256=digest), teacher=dict(sha256=e.reference.TEACHER_SHA)))
            fields = ['图片', 'split', 'annotation_status', 'label_review_required', 'scene_review_required', 'Small', 'Occluded', 'Blurred', 'No Ball']
            rows = [','.join(fields)]
            expected = {}
            for split in ('train', 'val'):
                image = data/'images'/split/(split+'.png'); image.parent.mkdir(parents=True)
                label = data/'labels'/split/(split+'.txt'); label.parent.mkdir(parents=True)
                Image.new('RGB', (64, 64)).save(image); label.write_text('0 0.5 0.5 0.25 0.25\n')
                for path in (image, label): expected[str(Path('/old/datasets/v1')/path.relative_to(data))] = e.sha(path)
                rows.append(','.join([image.name, split, 'reviewed_annotation', '0', '0', '1', '1', '0', '0']))
                listing = data/'lists'/f'{split}.txt'; listing.parent.mkdir(exist_ok=True); listing.write_text('/old/'+image.name+'\n')
            (data/'metadata.csv').write_text('\n'.join(rows)+'\n'); (data/'manifest.csv').write_text('fixture-index\n')
            # A Test payload exists, but opening it must be impossible in this test.
            forbidden = data/'images/test/never.png'; forbidden.parent.mkdir(); forbidden.write_bytes(b'never open')
            config = e.config_for(ref, True)
            (ref/'train.yaml').write_text(yaml.safe_dump(config))
            e.dump(ref/'train.effective.json', vars(get_cfg(overrides=config)))
            e.dump(ref/'library_contract.json', {'fixture': 'test'})
            e.dump(ref/'train_val_expected_hashes.json', expected)
            anchors = {str(Path('/old/datasets/v1')/p): e.sha(data/p) for p in ('manifest.csv', 'metadata.csv', 'lists/train.txt', 'lists/val.txt')}
            anchors.update({str(ref/f): e.sha(ref/f) for f in ('train.yaml', 'init.pt', 'library_contract.json', 'train_val_expected_hashes.json')})
            e.dump(ref/'protected_inputs.json', anchors)
            before = {str(p): e.sha(p) for p in ref.glob('*')}
            here = root/'E08'; here.mkdir()
            args = argparse.Namespace(e07_run=str(ref), e05_run=str(parent), init=None, data_root=str(data))
            original = Path.open
            def guarded(p, *a, **kw):
                if p == forbidden:
                    raise AssertionError('Test image opened')
                return original(p, *a, **kw)
            probe = e.reference.E05/'assets/yolo26n.pt'
            original_file = Path.is_file
            original_sha = e.sha
            def test_sha(path):
                if Path(path) == probe:
                    return e.load(e.reference.E05/'PRETRAINED.json')['sha256']
                return original_sha(path)
            with patch.object(e, 'HERE', here), patch.object(e, 'STUDENT_SHA', digest), \
                    patch.object(e, 'sha', side_effect=test_sha), \
                    patch.object(Path, 'is_file', lambda path: True if path == probe else original_file(path)), \
                    patch.object(e, 'runtime'), patch.object(e.base, 'COUNTS', dict(train=1, val=1)), patch.object(Path, 'open', guarded):
                e.prepare(args)
                run = e.run_path(None)
                self.assertEqual(e.sha(run/'init.pt'), digest)
                self.assertTrue(e.verify(run)['unchanged'])
                self.assertEqual(e.load(run/'run_record.json')['status'], 'prepared')
                self.assertFalse((run/'train').exists())
                e.dry_run(run)
                e.prepare(args)
                self.assertNotEqual(e.run_path(None), run)
            self.assertEqual(before, {str(p): e.sha(p) for p in ref.glob('*')})


class Evidence(unittest.TestCase):
    def fixture(self, root):
        run = root/'run'; run.mkdir()
        data = root/'data'; data.mkdir()
        import yaml
        from PIL import Image
        metadata = ['图片,split,annotation_status,label_review_required,scene_review_required,Small,Occluded,Blurred,No Ball']
        e.dump(run/'run_record.json', dict(data_root=str(data)))
        (run/'dataset.val-evaluation.yaml').write_text(yaml.safe_dump(dict(path=str(data), val='images/val', names={0: 'football'})))
        e.evaluation_revision(run)
        checkpoint = root/'model.pt'; checkpoint.write_bytes(b'fixture identity')
        directory = run/'comparison_fixture/E05'; directory.mkdir(parents=True)
        metrics = e.base.module('fixture_shared_metrics', run/'evaluation_code/eval_metrics.py')
        predictions, selected, frozen = [], [], {}
        for i in range(1223):
            image = data/'images/val'/f'{i:04}.png'; label = data/'labels/val'/f'{i:04}.txt'
            gt = [[0, 0, 10, 10]]*(2 if i < 42 else 1) if i < 813 else []
            flags = {'Small': int(i < 100), 'Occluded': int(i < 200), 'Blurred': 0, 'No Ball': int(not gt)}
            image.parent.mkdir(parents=True, exist_ok=True); label.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (16, 16)).save(image)
            label.write_text('0 0.3125 0.3125 0.625 0.625\n'*len(gt))
            status = 'reviewed_annotation' if gt else 'negative_confirmed'
            metadata.append(','.join([image.name, 'val', status, '0', '0', *map(str, flags.values())]))
            predictions.append(dict(image=str(image), width=16, height=16, gt=gt, boxes=[[0, 0, 10, 10]] if gt else [], scores=[.9] if gt else [], flags=flags))
            frozen[str(image)] = e.sha(image); frozen[str(label)] = e.sha(label)
            selected.append(dict(image=str(image), label=str(label), image_sha256=e.sha(image), label_sha256=e.sha(label)))
        (data/'metadata.csv').write_text('\n'.join(metadata)+'\n')
        e.dump(run/'train_val_expected_hashes.json', frozen)
        prepared = metrics.prepare(predictions)
        scenes = {name: metrics.summarize(subset, .45, .5)[0] for name, subset in metrics.groups(prepared).items()}
        args = e.base.evaluation_options(run, checkpoint, 'cpu', .45); args['metadata'] = str(data/'metadata.csv')
        result = dict(status='complete', input_files_verified_unchanged=True, split='val', partial_split=False,
            available_before_limit=1223, skipped_images=0, model_class_id=0, model=str(checkpoint), arguments=args,
            runtime=dict(backend_end2end=False, backend_fp16=False, actual_input_shape=[640, 640]),
            metrics=scenes['All'], scene_metrics=scenes, versions={'fixture': '1'})
        e.dump(directory/'metrics.json', result)
        e.dump(directory/'status.json', dict(status='complete', input_files_verified_unchanged=True))
        e.dump(directory/'inputs_manifest.json', dict(arguments=args, model_sha256=e.sha(checkpoint),
            dataset_yaml_sha256=e.sha(run/'dataset.val-evaluation.yaml'), metadata_sha256=e.sha(data/'metadata.csv'),
            evaluation_code_sha256={p.name: e.sha(p) for p in (run/'evaluation_code').glob('*.py')}, selected=selected))
        (directory/'predictions.jsonl').write_text(''.join(json.dumps(p)+'\n' for p in predictions))
        return run, directory, checkpoint

    def test_complete_metrics_recomputed_and_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            run, directory, checkpoint = self.fixture(Path(temp))
            result = compare.validate_evaluation(e, directory, run, checkpoint, 'cpu')
            self.assertEqual(result['metrics']['no_ball_images'], 410)
            self.assertEqual(result['metrics']['gt_boxes'], 855)
            result['scene_metrics']['Small']['recall'] = .123
            e.dump(directory/'metrics.json', result)
            with self.assertRaisesRegex(ValueError, 'cached metric differs'):
                compare.validate_evaluation(e, directory, run, checkpoint, 'cpu')

    def test_compare_reuses_only_verified_complete_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, directory, checkpoint = self.fixture(root)
            source = root/'E05'
            path = source/'train/weights/best.pt'; path.parent.mkdir(parents=True); path.write_bytes(checkpoint.read_bytes())
            e.dump(source/'run_record.json', {'status': 'trained', 'training': {'checkpoints': {'best': {'sha256': e.sha(path)}}}})
            (source/'train/results.csv').write_text('epoch,metrics/mAP50-95(B)\n1,0.5\n')
            record = e.load(run/'run_record.json'); record.update(status='prepared', e05_run=str(source), e07_run=str(root/'missing'))
            e.dump(run/'run_record.json', record)
            for filename in ('metrics.json', 'inputs_manifest.json'):
                doc = e.load(directory/filename)
                doc['arguments']['model'] = str(path)
                if filename == 'metrics.json': doc['model'] = str(path)
                e.dump(directory/filename, doc)
            with patch.object(e, 'verify'), patch.object(e, 'runtime'), patch.object(e, 'STUDENT_SHA', e.sha(path)), \
                    patch.object(compare.subprocess, 'run', side_effect=AssertionError('unexpected prediction')):
                out = compare.compare(e, run, evaluate=False, device='cpu')
                summary = e.load(out/'comparison.json')
                self.assertEqual(summary['models']['E05']['status'], 'complete')
                self.assertEqual(summary['models']['E08']['status'], 'not_run')
                self.assertEqual(summary['models']['E07']['status'], 'not_run')
                self.assertIn('metrics.json', summary['models']['E05']['evidence_sha256'])
                e.dump(directory/'status.json', dict(status='failed'))
                out = compare.compare(e, run, evaluate=False, device='cpu')
                self.assertEqual(e.load(out/'comparison.json')['models']['E05']['status'], 'not_run')

    def test_threshold_partial_split_and_prediction_order_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            run, directory, checkpoint = self.fixture(Path(temp))
            original = e.load(directory/'metrics.json')
            for key, value in [('partial_split', True), ('skipped_images', 1)]:
                e.dump(directory/'metrics.json', {**original, key: value})
                with self.assertRaises(ValueError): compare.validate_evaluation(e, directory, run, checkpoint, 'cpu')
            original['arguments']['conf'] = .25
            e.dump(directory/'metrics.json', original)
            with self.assertRaises(ValueError): compare.validate_evaluation(e, directory, run, checkpoint, 'cpu')
            original['arguments']['conf'] = .45; e.dump(directory/'metrics.json', original)
            path = directory/'predictions.jsonl'; path.write_text('\n'.join(path.read_text().splitlines()[::-1])+'\n')
            with self.assertRaises(ValueError): compare.validate_evaluation(e, directory, run, checkpoint, 'cpu')


if __name__ == '__main__': unittest.main()
