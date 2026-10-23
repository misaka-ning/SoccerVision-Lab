"""Exercise all four entry families across a YAML edit, without ML or Qt builds."""
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

SCRIPTS=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(SCRIPTS))
from common.dataset_config import load_dataset,materialize_yaml


class VersionSwitchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='dataset version ')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'relocated clone'
        scripts=self.root/'script'
        for relative in ('common/__init__.py','common/dataset_config.py','common/dataset_config.sh','model-training/train.py',
                         'model-training/config/train.yaml','model-evaluation/evaluate.py',
                         'model-evaluation/dataset_io.py','repository/verify_dataset.py',
                         'repository/prepare_data.py','dataset-reviewer/review_dataset.sh'):
            target=scripts/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(SCRIPTS/relative,target)
        self.config=scripts/'config.yaml'
        self.frozen=[]
        for version in ('v0','v1'):
            data=self.root/'datasets'/version
            rows=[]
            for kind in ('images','labels'):
                for split in ('train','val','test'):
                    (data/kind/split).mkdir(parents=True)
            for split in ('train','val','test'):
                if version=='v0' and split=='test':continue
                name=f'{version}_{split}.png'
                Image.new('RGB',(20,20),'green').save(data/'images'/split/name)
                (data/'labels'/split/Path(name).with_suffix('.txt')).write_text('0 .5 .5 .2 .2\n')
                rows.append({'图片':name,'split':split,'annotation_status':'reviewed_annotation',
                             'label_review_required':'0','scene_review_required':'0',
                             'Small':'1','Occluded':'0','Blurred':'0','No Ball':'0'})
            with (data/'metadata.csv').open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
            # Frozen configs deliberately refer to a machine that does not exist.
            (data/'dataset.yaml').write_text('path: /old/machine/missing\n')
            (data/'lists').mkdir();(data/'lists/train.txt').write_text('/old/frozen.png\n')
            self.frozen.extend([data/'dataset.yaml',data/'lists/train.txt',data/'metadata.csv'])
        (self.root/'baseline').mkdir()
        (self.root/'baseline/E0_original_best.pt').write_bytes(b'only dry-run: never deserialize')
        self.write_config('v0')
        self.hashes={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.frozen}
        self.env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','FOOTBALL_DATASET_PYTHON':sys.executable}
        self.env.pop('FOOTBALL_DATASET_CONFIG',None)

    def write_config(self,version):
        self.config.write_text(f'dataset_version: {version}\ndatasets:\n  v0:\n    root: datasets/v0\n  v1:\n    root: datasets/v1\n')

    def run_entry(self,relative,*args,expected=0,env=None):
        path=self.root/'script'/relative
        cmd=['bash',str(path),*args] if path.suffix=='.sh' else [sys.executable,'-B',str(path),*args]
        result=subprocess.run(cmd,cwd='/tmp',env=env or self.env,text=True,capture_output=True)
        self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
        return result

    def test_yaml_is_reread_in_same_process_and_output_is_relocated(self):
        first=load_dataset(root=self.root)
        materialize_yaml(first)
        self.write_config('v1')
        second=load_dataset(root=self.root)
        output=materialize_yaml(second)
        self.assertEqual(first['root'],self.root/'datasets/v0')
        self.assertEqual(second['root'],self.root/'datasets/v1')
        self.assertIn(str(second['root']),output.read_text())
        self.assertNotIn('/old/machine',output.read_text())
        self.assertEqual(self.hashes,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.frozen})

    def test_training_and_evaluation_switch_on_next_run_and_test_stays_empty_in_v0(self):
        for version in ('v0','v1'):
            self.write_config(version)
            result=self.run_entry('model-training/train.py','--dry-run')
            self.assertIn(str(self.root/'datasets'/version),result.stdout)
            result=self.run_entry('model-evaluation/evaluate.py','--model','baseline/E0_original_best.pt','--dry-run')
            self.assertIn(str(self.root/'datasets'/version),result.stdout)
            result=self.run_entry('model-evaluation/evaluate.py','--model','baseline/E0_original_best.pt','--split','test','--dry-run',expected=2 if version=='v0' else 0)
            self.assertIn('test 集为空' if version=='v0' else '集合test：1/1',result.stderr+result.stdout)

    def test_repository_defaults_switch_and_check_only_never_writes(self):
        for version in ('v0','v1'):
            self.write_config(version)
            result=self.run_entry('repository/verify_dataset.py')
            self.assertEqual(json.loads(result.stdout)['dataset_root'],str(self.root/'datasets'/version))
            self.run_entry('repository/prepare_data.py','--check-only')
            self.assertFalse((self.root/'experiments').exists())
        self.run_entry('repository/prepare_data.py')
        self.assertTrue((self.root/'experiments/configs/datasets/v1.dataset.yaml').is_file())

    def test_qt_launcher_switches_without_rebuilding_and_passes_gallery_options(self):
        product=self.root/'script/dataset-reviewer'
        (product/'src').mkdir()
        (product/'CMakeLists.txt').write_text('# fixture, no compile allowed\n')
        sdk=self.root/'fake sdk'
        (sdk/'lib/cmake/Qt6').mkdir(parents=True)
        (sdk/'lib/cmake/Qt6/Qt6Config.cmake').touch()
        (sdk/'plugins/platforms').mkdir(parents=True)
        build=product/'build/release';build.mkdir(parents=True)
        binary=build/'football-dataset-reviewer'
        binary.write_text('#!/usr/bin/env bash\nprintf "%s\\0" "$@"\n')
        binary.chmod(0o755)
        lock=build/'qt_review_lock_runner';lock.write_text('#!/usr/bin/env bash\nexit 99\n');lock.chmod(0o755)
        marker=build/'.review-qt-prefix';marker.write_text(str(sdk)+'\n')
        stamps={p:p.stat().st_mtime_ns for p in (binary,lock,marker)}
        for version in ('v0','v1'):
            self.write_config(version)
            result=self.run_entry('dataset-reviewer/review_dataset.sh','--gallery',env={**self.env,'QT_PREFIX':str(sdk)})
            self.assertIn('--dataset\x00'+str(self.root/'datasets'/version)+'\x00--gallery\x00',result.stdout)
            self.assertNotIn('正在构建',result.stdout)
        self.assertEqual(stamps,{p:p.stat().st_mtime_ns for p in stamps})

    def test_bad_version_does_not_fall_back_and_cli_override_is_explicit(self):
        self.write_config('typo')
        result=self.run_entry('common/dataset_config.py',expected=2)
        self.assertIn('未配置',result.stderr)
        result=self.run_entry('common/dataset_config.py','--version','v1')
        self.assertEqual(json.loads(result.stdout)['version'],'v1')
        self.assertIn('dataset_version: typo',self.config.read_text())


if __name__=='__main__':unittest.main()
