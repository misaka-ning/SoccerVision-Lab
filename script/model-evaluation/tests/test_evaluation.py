import contextlib
from collections import Counter
import re
import xml.etree.ElementTree as ET
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np
from PIL import Image

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from dataset_io import select,assert_unchanged
from eval_metrics import prepare,operating,average_precision,match,wilson
from evaluate import main,choose_class,parse_args
from eval_metrics import summarize,groups


def record(name,gt,boxes,scores):
    return dict(image=name,gt=gt,boxes=boxes,scores=scores,flags={'Small':0,'Occluded':0,'Blurred':0,'No Ball':int(not gt)})


class MetricTests(unittest.TestCase):
    def setUp(self):
        self.records=prepare([record('hit',[[0,0,10,10]],[[0,0,10,10]],[.9]),
                              record('negative',[],[[1,1,3,3],[4,4,6,6]],[.8,.7]),
                              record('miss',[[0,0,10,10]],[],[])])

    def test_object_counts_and_image_fpr_have_distinct_denominators(self):
        m=operating(self.records,.65,.5)
        self.assertEqual((m['TP'],m['FP'],m['FN']),(1,2,1))
        self.assertAlmostEqual(m['precision'],1/3)
        self.assertEqual(m['recall'],.5)
        self.assertEqual(m['no_ball_false_positive_images'],1)
        self.assertEqual(m['no_ball_false_positive_boxes'],2)
        self.assertEqual(m['no_ball_false_positive_rate'],1)
        self.assertEqual(m['no_ball_fp_boxes_per_image'],2)
        self.assertEqual(m['presence_confusion'],dict(TP=1,FP=1,FN=1,TN=0))

    def test_fixed_threshold_is_applied_before_rematching(self):
        # The low-score, higher-IoU duplicate must not steal the high-score TP.
        # Deliberately unsorted exported-model output: the low-score box is first.
        rows=prepare([record('duplicate',[[0,0,10,10]],[[0,0,10,10],[0,0,9,10]],[.2,.9])])
        self.assertEqual(rows[0]['correct'][:,0].tolist(),[True,False])
        m=operating(rows,.5,.5)
        self.assertEqual((m['TP'],m['FP'],m['FN']),(1,0,0))

    def test_one_prediction_cannot_match_two_balls(self):
        rows=prepare([record('two',[[0,0,10,10],[0,0,10,10]],[[0,0,10,10]],[.9])])
        m=operating(rows,.5,.5)
        self.assertEqual((m['TP'],m['FN']),(1,1))

    def test_zero_denominators_are_not_fake_successes(self):
        negatives=prepare([record('blank',[],[],[])])
        m=operating(negatives,.25,.5)
        self.assertIsNone(m['recall']);self.assertIsNone(m['precision'])
        self.assertEqual(m['no_ball_false_positive_rate'],0)
        ap,pr=average_precision(negatives)
        self.assertIsNone(ap['mAP50']);self.assertIsNone(pr)
        m=operating([self.records[0]],.25,.5)
        self.assertIsNone(m['no_ball_false_positive_rate'])
        self.assertIsNone(wilson(0,0))

    def test_empty_predictions_with_ground_truth_are_zero_recall(self):
        rows=prepare([record('miss',[[0,0,10,10]],[],[])])
        m=operating(rows,.25,.5)
        self.assertEqual((m['precision'],m['recall']),(0.,0.))
        self.assertEqual(average_precision(rows)[0]['mAP50'],0.)

    def test_matcher_agrees_with_installed_ultralytics_reference(self):
        import torch
        from types import SimpleNamespace
        from ultralytics.engine.validator import BaseValidator
        rng=np.random.default_rng(42)
        thresholds=torch.linspace(.5,.95,10)
        for targets,preds in ((0,0),(0,4),(2,0),(1,6),(5,8)):
            iou=rng.random((targets,preds),dtype=np.float32)
            ref=BaseValidator.match_predictions(SimpleNamespace(iouv=thresholds),torch.zeros(preds),torch.zeros(targets),torch.from_numpy(iou)).numpy()
            np.testing.assert_array_equal(match(iou,thresholds.numpy()),ref)

    def test_perfect_predictions_have_near_unit_ap_and_bad_ranking_reduces_it(self):
        good=prepare([record('hit',[[0,0,10,10]],[[0,0,10,10]],[.9])])
        self.assertGreater(average_precision(good)[0]['mAP50'],.99)
        bad=good+prepare([record('false',[],[[0,0,10,10]],[.99])])
        self.assertLess(average_precision(bad)[0]['mAP50'],average_precision(good)[0]['mAP50'])

    def test_multiclass_model_needs_explicit_mapping(self):
        self.assertEqual(choose_class({0:'football'},None),0)
        with self.assertRaises(ValueError):choose_class({0:'person',32:'sports ball'},None)
        self.assertEqual(choose_class({0:'person',32:'sports ball'},32),32)
        with self.assertRaises(ValueError):choose_class({0:'football'},32)


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'datasets';self.root.mkdir()
        self.data=self.root/'dataset.yaml';self.data.write_text(f'path: {self.root}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: football\n')
        for split in ('train','val','test'):
            (self.root/'images'/split).mkdir(parents=True);(self.root/'labels'/split).mkdir(parents=True)
        self.rows=[]
        for i,status in enumerate(('reviewed_annotation','negative_confirmed','reviewed_excluded','auto_label_needs_review')):
            name=f'frame_{i}.png';Image.new('RGB',(20,20),'gray').save(self.root/'images/val'/name)
            (self.root/'labels/val'/f'frame_{i}.txt').write_text('0 0.5 0.5 0.5 0.5\n' if i==0 else '')
            self.rows.append({'图片':name,'split':'val','annotation_status':status,
                             'label_review_required':'1' if i==3 else '0','scene_review_required':'0',
                             'Small':'0','Occluded':'0','Blurred':'0','No Ball':'0' if i==0 else '1'})
        self.write_meta()

    def write_meta(self):
        with (self.root/'metadata.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=self.rows[0]);w.writeheader();w.writerows(self.rows)

    def test_selection_excludes_unusable_and_pending(self):
        s=select(self.data,'val')
        self.assertEqual([p.image.name for p in s.samples],['frame_0.png','frame_1.png'])
        self.assertEqual({r['reason'] for r in s.skipped},{'reviewed_excluded','review_pending'})
        assert_unchanged(s)
        self.assertFalse(list(self.root.rglob('*.cache')))

    def test_empty_test_does_not_silently_fall_back_to_val(self):
        with self.assertRaisesRegex(ValueError,'test 集为空'):select(self.data,'test')

    def test_missing_label_is_not_a_negative(self):
        (self.root/'labels/val/frame_1.txt').unlink()
        with self.assertRaisesRegex(ValueError,'缺少label'):select(self.data,'val')

    def test_inconsistent_no_ball_and_out_of_bounds_rejected(self):
        self.rows[0]['No Ball']='1';self.write_meta()
        with self.assertRaisesRegex(ValueError,'No Ball'):select(self.data,'val')
        self.rows[0]['No Ball']='0';self.write_meta()
        (self.root/'labels/val/frame_0.txt').write_text('0 .01 .5 .2 .2\n')
        with self.assertRaisesRegex(ValueError,'越界'):select(self.data,'val')

    def test_source_change_is_detected(self):
        selection=select(self.data,'val')
        (self.root/'labels/val/frame_1.txt').write_text('0 .5 .5 .2 .2\n')
        with self.assertRaises(RuntimeError):assert_unchanged(selection)

    def test_dry_run_creates_no_output_and_never_loads_checkpoint(self):
        model=Path(self.temp.name)/'dummy.pt';model.write_bytes(b'not-a-checkpoint')
        out=Path(self.temp.name)/'result'
        with contextlib.redirect_stdout(io.StringIO()):
            result=main(['--model',str(model),'--data',str(self.data),'--output',str(out),'--dry-run'])
        self.assertEqual(result,0);self.assertFalse(out.exists())
        with contextlib.redirect_stderr(io.StringIO()),contextlib.redirect_stdout(io.StringIO()):
            result=main(['--model',str(model),'--data',str(self.data),'--output',str(self.root/'bad'),'--dry-run'])
        self.assertEqual(result,2)

    def test_invalid_thresholds_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            parse_args(['--model','x.pt','--min-conf','.9','--conf','.2'])


class ReportTests(unittest.TestCase):
    def test_paper_outputs_are_readable_and_counts_match_the_exported_tables(self):
        from reporting import save_report
        miss=record('miss',[[0,0,10,10]],[],[]);miss['flags']['Small']=1
        rows=prepare([record('hit',[[0,0,10,10]],[[0,0,10,10]],[.9]),
                      record('negative',[],[[1,1,3,3],[4,4,6,6]],[.8,.7]),
                      miss,record('clean_negative',[],[],[])])
        metrics,pr=summarize(rows,.65,.5)
        summary=dict(model='/fixture/weights.pt',model_name='model_&_test%',model_class_id=0,split='val',
                     skipped_images=0,metrics=metrics,versions={'ultralytics':'fixture'},partial_split=False,
                     available_before_limit=len(rows),runtime={})
        args=SimpleNamespace(conf=.65,min_conf=.001,match_iou=.5,nms_iou=.7,imgsz=640,max_det=300,formats='png,pdf,svg',dpi=80)
        group_metrics={k:summarize(v,.65,.5)[0] for k,v in groups(rows).items()}
        per_image=[]
        for r in rows:
            m=operating([r],.65,.5)
            per_image.append(dict(image=r['image'],**{k:m[k] for k in ('gt_boxes','predicted_boxes','TP','FP','FN')}))
        for requested in (None,'svg','pdf','png,pdf,svg'):
            with self.subTest(formats=requested),tempfile.TemporaryDirectory() as tmp:
                options=['--model','fixture.pt']+(['--formats',requested] if requested else [])
                args.formats=parse_args(options).formats
                expected_formats=set(requested.split(',')) if requested else {'png'}
                out=Path(tmp)
                save_report(out,summary,group_metrics,[operating(rows,c,.5) for c in (.001,.65,1)],rows,per_image,pr,args)
                files=list((out/'figures').iterdir())
                self.assertEqual(len(files),8*len(expected_formats))
                self.assertEqual({p.suffix[1:] for p in files},expected_formats)
                for p in (out/'figures').glob('*.png'):
                    with Image.open(p) as im:im.verify()
                if 'pdf' in expected_formats:
                    self.assertTrue((out/'figures/pr_curve.pdf').read_bytes().startswith(b'%PDF'))
                if 'svg' in expected_formats:
                    texts=[''.join(node.itertext()) for node in ET.parse(out/'figures/scene_comparison.svg').iter() if node.tag.endswith('}text')]
                    values=[m[k] for m in group_metrics.values() for k in ('mAP50','recall','no_ball_false_positive_rate')]
                    expected_labels=Counter(f'{v:.2%}' for v in values if v is not None)
                    self.assertEqual(Counter(t for t in texts if re.fullmatch(r'\d+\.\d{2}%',t)),expected_labels)
                    self.assertEqual(texts.count('NA'),sum(v is None for v in values))
                    self.assertIn('0.00%',texts);self.assertIn('100.00%',texts)
                result=json.loads((out/'metrics.json').read_text())
                self.assertEqual(result['metrics']['no_ball_false_positive_images'],1)
                with (out/'false_positive_no_ball.csv').open(encoding='utf-8-sig',newline='') as f:failures=list(csv.DictReader(f))
                self.assertEqual(len(failures),1);self.assertEqual(failures[0]['FP'],'2')
                tex=(out/'tables/paper_row.tex').read_text()
                self.assertIn(r'model\_\&\_test\%',tex)
                self.assertTrue(tex.splitlines()[-1].endswith('\\\\'))



if __name__=='__main__':unittest.main()
