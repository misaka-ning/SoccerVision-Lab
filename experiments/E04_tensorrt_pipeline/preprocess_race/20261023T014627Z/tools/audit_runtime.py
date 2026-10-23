"""Read-only source/dependency/data audit. Does not load an Engine or camera."""
import ast
import hashlib
import importlib.metadata as meta
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tarfile

project=Path('/home/nvidia/soccer_backend_tensorrt')
old=project/'results/E04_tensorrt_pipeline/20261022T020842Z_78f1b7'
result={'python':sys.executable,'packages':{},'specs':{},'files':{},'data':{},'installed_matches':{}}
paths=[]
for name in ['numpy','opencv-python','torch','torchvision','ultralytics','tensorrt']:
 try:result['packages'][name]=meta.version(name)
 except meta.PackageNotFoundError:result['packages'][name]=None
for name in ['ultralytics','vpi','cv2','torch']:
 try:
  spec=importlib.util.find_spec(name);result['specs'][name]=None if spec is None else spec.origin
 except Exception as exc:result['specs'][name]=repr(exc)
ultra=result['specs']['ultralytics']
if ultra:
 root=Path(ultra).parent
 for rel in ['engine/predictor.py','data/augment.py','models/yolo/detect/predict.py']:
  p=root/rel
  if p.is_file():
   paths.append((p,'library/'+rel))
   result['files'][str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
for rel in ['adapters/yolo.py','optimizations/graph.py','optimizations/postprocess.py','optimizations/preprocess.py','pipeline.py','adapters/zed.py']:
 source=project/'soccer_perception_ros/soccer_perception'/rel
 installed=project/'install/soccer_perception_ros/lib/python3.8/site-packages/soccer_perception'/rel
 result['installed_matches'][rel]=installed.is_file() and hashlib.sha256(source.read_bytes()).digest()==hashlib.sha256(installed.read_bytes()).digest()
for p in (old/'stage0_golden_attempt1').glob('*'):
 if p.name in ['golden.json','effective_runtime.json','calibration.json']:
  paths.append((p,'golden_meta/'+p.name))
if old.exists():
 result['data']['old_root_entries']=[p.name for p in old.iterdir() if p.is_dir()]
 result['data']['golden_exists']=(old/'stage0_golden_attempt1/golden.json').is_file()
 # Inspect only frozen Val manifests, never search/read image Test directories.
 for p in old.glob('**/val_cases/manifest.json'):
  result['data'].setdefault('val_manifests',[]).append(str(p))
  paths.append((p,'val_meta/'+str(len(result['data']['val_manifests']))+'_manifest.json'))
  if len(result['data']['val_manifests'])>=3:break
for name in ['manifest.json','contract.json','val_pairs.json']:
 p=old/name
 if p.is_file():paths.append((p,'root_meta/'+name))
try:
 output=subprocess.run(['dpkg-query','-W','-f=${Package} ${Version}\n','*vpi*','*nvbuf*'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
 result['vpi_packages']=output.stdout
except Exception as exc:result['vpi_packages']=repr(exc)
# Report existing GPU source candidates only, without importing or running them.
result['cuda_candidates']=[str(p) for p in (project/'experiments').glob('**/compare_resize_numerical.py')]
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as tar:
 raw=json.dumps(result,indent=2).encode()
 import io
 info=tarfile.TarInfo('audit.json');info.size=len(raw);tar.addfile(info,io.BytesIO(raw))
 for p,name in paths:tar.add(str(p),arcname=name,recursive=False)
