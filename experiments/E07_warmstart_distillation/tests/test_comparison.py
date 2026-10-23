"""Check optional E06 inclusion without GPU work or fabricated evaluation outputs."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('e07_comparison',HERE/'e07.py')
e07=importlib.util.module_from_spec(spec);spec.loader.exec_module(e07)


class Comparison(unittest.TestCase):
    def exercise(self,status,mutate_reference=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);run=root/'E07/run';reference=root/'E06/run';cache=root/'cache'
            best=run/'train/weights/best.pt';ref_best=reference/'train/weights/best.pt'
            for p in (best,ref_best):p.parent.mkdir(parents=True);p.write_bytes(p.as_posix().encode())
            for name in ('E01_s','E05_n'):(cache/name).mkdir(parents=True)
            e07.dump(run/'run_record.json',dict(status='trained',E06_reference_run=str(reference),
                training=dict(checkpoints=dict(best=dict(sha256=e07.sha(best))))))
            e07.dump(reference/'run_record.json',dict(status=status,
                training=dict(checkpoints=dict(best=dict(sha256=e07.sha(ref_best))))))
            result=dict(metrics=dict(mAP50=.9,mAP50_95=.8,recall=.85,no_ball_false_positive_rate=.01),
                scene_metrics=dict(Small=dict(recall=.8),Occluded=dict(recall=.7)))
            models=[]
            def predict(command,check):
                self.assertTrue(check)
                models.append(command[command.index('--model')+1])
                Path(command[command.index('--output')+1]).mkdir()
                if mutate_reference:ref_best.write_bytes(b'changed after validation')
            with patch.object(e07,'runtime'),patch.object(e07,'verify',return_value={}),patch.object(e07,'E06_RUN',reference),\
                    patch.object(e07,'VAL',cache),patch.object(e07.base,'completed_evaluation',return_value=result),\
                    patch.object(e07.subprocess,'run',side_effect=predict):
                if mutate_reference:
                    with self.assertRaisesRegex(ValueError,'E06对照权重变化'):e07.evaluate(run,'0',.45)
                    return
                e07.evaluate(run,'0',.45)
            output=next(run.glob('val_*/comparison.json'))
            summary=e07.load(output)
            self.assertIn(str(best),models)
            self.assertEqual(str(ref_best) in models,status=='trained')
            self.assertEqual('E06_KD1' in summary['models'],status=='trained')
            text=output.with_name('COMPARISON.md').read_text()
            self.assertIn('额外训练和蒸馏',text)
            if status!='trained':self.assertIn('尚未训练完成',text)

    def test_unfinished_e06_is_marked_without_fake_measurement(self):self.exercise('prepared')
    def test_finished_e06_is_evaluated_and_included(self):self.exercise('trained')
    def test_reference_change_aborts_comparison(self):self.exercise('trained',mutate_reference=True)


if __name__=='__main__':unittest.main()
