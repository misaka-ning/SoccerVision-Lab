"""Regression checks for CUDA environment selection and early failure."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PRODUCT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PRODUCT))
import check_runtime


class RuntimeTests(unittest.TestCase):
    def test_cpu_build_does_not_accept_a_gpu_request(self):
        torch=SimpleNamespace(__version__='test+cpu',version=SimpleNamespace(cuda=None))
        with patch.object(check_runtime.importlib.metadata,'version',return_value='fixture'),patch.dict(sys.modules,torch=torch):
            with self.assertRaisesRegex(ValueError,'CPU版'):check_runtime.check('0')
            self.assertIn('CPU',check_runtime.check('cpu'))

    def test_cuda_visibility_and_device_range_are_checked(self):
        cuda=SimpleNamespace(is_available=lambda:False,device_count=lambda:1,get_device_name=lambda i:'Fixture GPU')
        torch=SimpleNamespace(__version__='test+cu128',version=SimpleNamespace(cuda='12.8'),cuda=cuda)
        with patch.object(check_runtime.importlib.metadata,'version',return_value='fixture'),patch.dict(sys.modules,torch=torch):
            with self.assertRaisesRegex(ValueError,'无法访问GPU'):check_runtime.check('0')
            cuda.is_available=lambda:True
            with self.assertRaisesRegex(ValueError,'只可见1张'):check_runtime.check('1')
            self.assertIn('Fixture GPU',check_runtime.check('0'))


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='evaluation-launcher-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.launcher=self.root/'evaluate.sh'
        shutil.copyfile(PRODUCT/'evaluate.sh',self.launcher)
        self.model=self.root/'model with spaces.pt';self.model.touch()
        self.log=self.root/'calls.jsonl'
        self.env={**os.environ,'HOME':str(self.root),'EVAL_TEST_LOG':str(self.log),'PYTHONDONTWRITEBYTECODE':'1'}
        self.env.pop('FOOTBALL_EVAL_PYTHON',None)
        self.gpu=self.root/'.local/share/vision-studio/gpu-runtime/bin/python'
        self.fake_python(self.gpu)

    def fake_python(self,path):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('#!'+sys.executable+'\n'+'''import json,os,sys
with open(os.environ['EVAL_TEST_LOG'],'a') as stream:stream.write(json.dumps({'python':sys.argv[0],'args':sys.argv[1:]})+'\\n')
if any(v.endswith('check_runtime.py') for v in sys.argv) and os.environ.get('EVAL_TEST_FAIL_CHECK'):
    print('fixture CUDA check failed',file=sys.stderr)
    sys.exit(2)
''')
        path.chmod(0o755)

    def run_launcher(self,*args):
        result=subprocess.run(['bash',str(self.launcher),*args],input='"'+str(self.model)+'"\n',env=self.env,text=True,capture_output=True)
        calls=[json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return result,calls

    def test_default_gpu_runtime_and_arguments_are_forwarded(self):
        result,calls=self.run_launcher('--class-id','32')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0]['python'],str(self.gpu))
        self.assertTrue(calls[0]['args'][1].endswith('check_runtime.py'))
        self.assertEqual(calls[0]['args'][-2:],['--device','0'])
        self.assertIn(str(self.model),calls[1]['args'])
        self.assertEqual(calls[1]['args'][-4:],['--device','0','--class-id','32'])

    def test_explicit_python_and_cpu_device_take_precedence(self):
        override=self.root/'custom runtime/python';self.fake_python(override)
        self.env['FOOTBALL_EVAL_PYTHON']=str(override)
        result,calls=self.run_launcher('--device=cpu')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(all(c['python']==str(override) for c in calls))
        self.assertEqual(calls[0]['args'][-2:],['--device','cpu'])
        self.assertEqual(calls[1]['args'][-3:],['--device','cpu','--device=cpu'])

    def test_bad_runtime_stops_before_model_prompt_or_evaluation(self):
        self.env['EVAL_TEST_FAIL_CHECK']='1'
        result,calls=self.run_launcher()
        self.assertEqual(result.returncode,2)
        self.assertEqual(len(calls),1)
        self.assertNotIn('请输入模型路径',result.stderr+result.stdout)

    def test_dry_run_and_help_do_not_probe_cuda(self):
        self.env['EVAL_TEST_FAIL_CHECK']='1'
        result,calls=self.run_launcher('--dry-run')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(calls),1)
        self.assertTrue(calls[0]['args'][1].endswith('evaluate.py'))
        self.log.unlink()
        result,calls=self.run_launcher('--help')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(calls[0]['args'][-1],'--help')


if __name__=='__main__':unittest.main()
