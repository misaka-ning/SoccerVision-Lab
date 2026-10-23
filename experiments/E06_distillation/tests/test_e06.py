import fcntl
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('e06',HERE/'e06.py')
e06=importlib.util.module_from_spec(spec)
spec.loader.exec_module(e06)


class Guards(unittest.TestCase):
    def test_only_teacher_and_distillation_weight_added_to_recipe(self):
        run=Path('/tmp/e06-recipe')
        original=e06.base.recipe(run)
        candidate=e06.training_config(run)
        self.assertEqual({k:v for k,v in candidate.items() if k not in ('distill_model','dis')},original)
        self.assertEqual(candidate['distill_model'],str(e06.TEACHER))
        self.assertEqual(candidate['dis'],6.0)
        self.assertTrue(candidate['nms'])
        self.assertEqual((candidate['batch'],candidate['imgsz'],candidate['seed']),(8,640,42))

    def test_model_and_data_tampering_cannot_be_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            run=Path(temp)
            teacher=run/'teacher.pt';teacher.write_bytes(b'frozen teacher')
            image=run/'train.png';image.write_bytes(b'frozen image')
            e06.dump(run/'protected_inputs.json',{str(teacher):e06.sha(teacher)})
            e06.dump(run/'train_val_expected_hashes.json',{str(image):e06.sha(image)})
            self.assertTrue(e06.verify(run)['unchanged'])
            image.write_bytes(b'changed image')
            with self.assertRaises(ValueError):e06.verify(run)
            image.write_bytes(b'frozen image')
            teacher.write_bytes(b'changed teacher')
            with self.assertRaises(ValueError):e06.verify(run)

    def test_e05_and_e06_cannot_train_concurrently(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'E05';current=root/'E06'
            old.mkdir();current.mkdir()
            with (old/'.training.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with patch.object(e06,'E05',old),patch.object(e06,'HERE',current),self.assertRaises(ValueError):
                    with e06.gpu_lock():self.fail('must not acquire GPU lock')

    def test_run_cannot_point_to_e05_or_production(self):
        for path in ['/tmp',str(e06.PARENT),'/home/nvidia/soccer_backend_tensorrt']:
            with self.assertRaises(ValueError):e06.run_path(path)


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
        self.assertEqual(e06.gradient_stats(model,65536)['tensors'],0)
        model.weight.grad=torch.full_like(model.weight,float('inf'))
        result=e06.gradient_stats(model,65536)
        self.assertEqual(result['tensors'],1)
        self.assertEqual(result['nonfinite_tensors'],1)
        self.assertIsNone(result['unscaled_norm'])

    def test_gradient_norm_accounts_for_amp_scale(self):
        import torch
        model=torch.nn.Linear(2,1,bias=False)
        model.weight.grad=torch.full_like(model.weight,8)
        result=e06.gradient_stats(model,8)
        self.assertEqual(result['nonfinite_tensors'],0)
        self.assertAlmostEqual(result['unscaled_norm'],2**.5,places=6)


if __name__=='__main__':unittest.main()
