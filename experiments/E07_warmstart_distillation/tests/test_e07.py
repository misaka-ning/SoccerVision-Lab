import fcntl
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('e07',HERE/'e07.py')
e07=importlib.util.module_from_spec(spec)
spec.loader.exec_module(e07)


class Guards(unittest.TestCase):
    def test_only_teacher_and_distillation_weight_added_to_recipe(self):
        run=Path('/tmp/e07-recipe')
        original=e07.base.recipe(run)
        candidate=e07.training_config(run)
        self.assertEqual({k:v for k,v in candidate.items() if k not in ('distill_model','dis')},original)
        self.assertEqual(candidate['distill_model'],str(e07.TEACHER))
        self.assertEqual(candidate['dis'],6.0)
        self.assertTrue(candidate['nms'])
        self.assertEqual((candidate['batch'],candidate['imgsz'],candidate['seed']),(8,640,42))

    def test_warm_start_uses_exact_e05_best_not_original_or_last(self):
        self.assertEqual(e07.STUDENT_INIT,e07.STUDENT_BEST)
        self.assertEqual(e07.STUDENT_INIT.name,'best.pt')
        self.assertEqual(e07.sha(e07.STUDENT_INIT),e07.STUDENT_INIT_SHA)
        self.assertNotEqual(e07.STUDENT_INIT_SHA,e07.sha(e07.PARENT/'init.pt'))
        self.assertEqual(e07.sha(e07.TEACHER),e07.TEACHER_SHA)

    def test_e06_source_and_prepared_inputs_are_preserved(self):
        provenance=e07.load(HERE/'DERIVATION.json')
        self.assertEqual(e07.sha(e07.E06/'e06.py'),provenance['source_sha256'])
        protected=e07.load(e07.E06_RUN/'protected_inputs.json')
        for filename in ('e06.py','start_training.sh','status.sh'):
            path=e07.E06/filename
            self.assertEqual(e07.sha(path),protected[str(path)])
        self.assertEqual(e07.sha(e07.E06_RUN/'init.pt'),e07.sha(e07.PARENT/'init.pt'))

    def test_e06_and_e07_recipes_differ_only_in_output_paths(self):
        spec=importlib.util.spec_from_file_location('e07_comparison_e06',e07.E06/'e06.py')
        baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
        here=e07.training_config(Path('/tmp/same-run'))
        there=baseline.training_config(Path('/tmp/same-run'))
        self.assertEqual(here,there)

    def test_e06_and_e07_share_the_gpu_lock(self):
        spec=importlib.util.spec_from_file_location('e07_lock_e06',e07.E06/'e06.py')
        baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'E05';cold=root/'E06';warm=root/'E07'
            for p in (old,cold,warm):p.mkdir()
            with patch.object(baseline,'E05',old),patch.object(baseline,'HERE',cold),patch.object(e07,'E05',old),patch.object(e07,'HERE',warm):
                with baseline.gpu_lock():
                    with self.assertRaises(ValueError):
                        with e07.gpu_lock():self.fail('concurrent GPU work')
                with e07.gpu_lock():
                    with self.assertRaises(ValueError):
                        with baseline.gpu_lock():self.fail('concurrent GPU work')

    def test_model_and_data_tampering_cannot_be_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            run=Path(temp)
            teacher=run/'teacher.pt';teacher.write_bytes(b'frozen teacher')
            image=run/'train.png';image.write_bytes(b'frozen image')
            e07.dump(run/'protected_inputs.json',{str(teacher):e07.sha(teacher)})
            e07.dump(run/'train_val_expected_hashes.json',{str(image):e07.sha(image)})
            self.assertTrue(e07.verify(run)['unchanged'])
            image.write_bytes(b'changed image')
            with self.assertRaises(ValueError):e07.verify(run)
            image.write_bytes(b'frozen image')
            teacher.write_bytes(b'changed teacher')
            with self.assertRaises(ValueError):e07.verify(run)

    def test_e05_and_e07_cannot_train_concurrently(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'E05';current=root/'E07'
            old.mkdir();current.mkdir()
            with (old/'.training.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with patch.object(e07,'E05',old),patch.object(e07,'HERE',current),self.assertRaises(ValueError):
                    with e07.gpu_lock():self.fail('must not acquire GPU lock')

    def test_run_cannot_point_to_e05_or_production(self):
        for path in ['/tmp',str(e07.PARENT),'/home/nvidia/soccer_backend_tensorrt']:
            with self.assertRaises(ValueError):e07.run_path(path)


class NativeFeatureLoss(unittest.TestCase):
    def test_confidence_weighted_loss_has_student_gradient(self):
        import torch
        from ultralytics.nn.distill_model import DistillationModel
        student=torch.ones(2,4,2,2,requires_grad=True)
        teacher=torch.zeros_like(student).detach()
        score=torch.ones(2,1,4)
        loss=DistillationModel.loss_sl2(None,student,teacher,0,(score,))
        self.assertAlmostEqual(float(loss.detach()),1.0)
        loss.backward()
        self.assertTrue(torch.isfinite(student.grad).all())
        self.assertGreater(float(student.grad.abs().sum()),0)
        self.assertIsNone(teacher.grad)

    def test_zero_teacher_confidence_stays_finite(self):
        import torch
        from ultralytics.nn.distill_model import DistillationModel
        student=torch.ones(2,4,2,2,requires_grad=True)
        loss=DistillationModel.loss_sl2(None,student,torch.zeros_like(student).detach(),0,(torch.zeros(2,1,4),))
        self.assertEqual(float(loss.detach()),0)
        loss.backward()
        self.assertTrue(torch.isfinite(student.grad).all())

    def test_scaled_overflow_is_distinguished_from_missing_gradient(self):
        import torch
        model=torch.nn.Linear(2,1,bias=False)
        self.assertEqual(e07.gradient_stats(model,65536)['tensors'],0)
        model.weight.grad=torch.full_like(model.weight,float('inf'))
        result=e07.gradient_stats(model,65536)
        self.assertEqual(result['tensors'],1)
        self.assertEqual(result['nonfinite_tensors'],1)
        self.assertIsNone(result['unscaled_norm'])

    def test_gradient_norm_accounts_for_amp_scale(self):
        import torch
        model=torch.nn.Linear(2,1,bias=False)
        model.weight.grad=torch.full_like(model.weight,8)
        result=e07.gradient_stats(model,8)
        self.assertEqual(result['nonfinite_tensors'],0)
        self.assertAlmostEqual(result['unscaled_norm'],2**.5,places=6)


if __name__=='__main__':unittest.main()
