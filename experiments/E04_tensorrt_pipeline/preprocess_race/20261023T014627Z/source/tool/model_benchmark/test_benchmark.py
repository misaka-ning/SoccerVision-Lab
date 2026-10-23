"""CPU-only validation: configuration, aggregation, serial supervision and timeout."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import benchmark
from reporting import generate, percentile


class Tests(unittest.TestCase):
    def test_single_model_config_and_shape_validation(self):
        import yaml
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'model.engine').write_bytes(b'fixture')
            cfg={'models':[{'name':'solo','path':'model.engine'}]}
            p=root/'config.yaml'; p.write_text(yaml.safe_dump(cfg))
            loaded=benchmark.load_config(p)
            self.assertEqual(loaded['baseline'],'solo')
            self.assertEqual(loaded['models'][0]['path'],str(root/'model.engine'))
            cfg['test']={'input_shape':[2,3,-1,640]}
            p.write_text(yaml.safe_dump(cfg))
            with self.assertRaises(ValueError): benchmark.load_config(p)

    def test_mismatched_shapes_rejected(self):
        a={'input_shape':[2,3,640,640], 'bindings':[], 'metadata':{}}
        b=dict(a,input_shape=[1,3,640,640])
        with self.assertRaises(ValueError):
            benchmark.compare_infos({'a':a,'b':b},{'test':{'mode':'engine'}})

    def test_percentile(self):
        self.assertAlmostEqual(percentile([10,20,30,40], .95), 38.5)

    def test_duplicate_yaml(self):
        import yaml
        with self.assertRaises(ValueError):
            yaml.load('models: []\nmodels: []', Loader=benchmark.UniqueLoader)

    def test_warmup_and_incomplete_not_pooled(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); jobs=[]
            for i,(status,offset) in enumerate([('complete',0),('complete',100),('failed',200)]):
                p=root/str(i); p.mkdir()
                (p/'frames.csv').write_text('cycle_start,cycle_end,publish_end,read_ready_to_publish_ms\n%d,%d,%d,10\n%d,%d,%d,20\n' % (offset,offset+1,offset+1,offset+1,offset+2,offset+2))
                jobs.append(dict(model='E1',mode='system',round=i+1,status=status,directory=str(p)))
            result=generate(root,{'baseline':'E1','test':{'rounds':3}},jobs,'failed')
            item=result['summary'][0]
            self.assertEqual(item['samples'],4)
            self.assertEqual(item['metrics']['processing_hz'],1)
            self.assertEqual(item['metrics']['publish_hz'],1)
            self.assertEqual(item['metrics']['read_ready_to_publish_ms']['mean'],15)
            self.assertNotIn('comparison',item)

    def test_supervisor_timeout_reaps_before_next(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'worker.py').write_text('import time\ntime.sleep(120)\n')
            cfg={'system':{'ros_domain_id':87},'monitor':{'progress_interval_seconds':.1,'stall_warning_seconds':.1,'stall_timeout_seconds':.3,'startup_timeout_seconds':.3,'shutdown_timeout_seconds':.3}}
            with patch.object(benchmark,'HERE',root):
                a=benchmark.run_worker(root,cfg,{'name':'a'},'engine',1)
                b=benchmark.run_worker(root,cfg,{'name':'b'},'engine',1)
            self.assertEqual(a['status'],'timeout'); self.assertEqual(b['status'],'timeout')
            self.assertTrue((root/'01_a_engine/controller_result.json').is_file())

    def test_exit_success_without_marker_is_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'worker.py').write_text('pass\n')
            cfg={'system':{'ros_domain_id':87},'monitor':{'progress_interval_seconds':.1,'stall_warning_seconds':.1,'stall_timeout_seconds':1,'startup_timeout_seconds':1,'shutdown_timeout_seconds':.3}}
            with patch.object(benchmark,'HERE',root):
                result=benchmark.run_worker(root,cfg,{'name':'a'},'engine',1)
            self.assertEqual(result['status'],'failed')


if __name__=='__main__': unittest.main()
