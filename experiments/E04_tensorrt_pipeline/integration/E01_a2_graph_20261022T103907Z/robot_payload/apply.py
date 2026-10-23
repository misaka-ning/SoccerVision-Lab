"""Apply a reviewed file manifest, refusing concurrent changes; no model loading."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

stage = Path(__file__).resolve().parent
project = Path('/home/nvidia/soccer_backend_tensorrt')
manifest = json.loads((stage / 'manifest.json').read_text())
def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
for item in manifest:
    rel = Path(item['path'])
    if rel.is_absolute() or '..' in rel.parts or 'models' in rel.parts:
        raise RuntimeError('Disallowed payload path: ' + str(rel))
    target = project / rel
    if target.is_symlink() or digest(target) != item['before_sha256']:
        raise RuntimeError('Robot file changed since read-only snapshot: ' + str(rel))
    if digest(stage / 'files' / rel) != item['sha256']:
        raise RuntimeError('Payload hash mismatch: ' + str(rel))
backup = stage / 'backup'
backup.mkdir(exist_ok=False)
engine = project / 'soccer_perception_ros/models/E01_baseline.engine'
weight = project / 'soccer_perception_ros/models/E01_baseline.pt'
expected_engine = '98c1b6bc703b29874d95db94d9cf51ef5b4a4142a7ca6cf22362a0c616fbf348'
if digest(engine) != expected_engine:
    raise RuntimeError('E01 engine changed; no files applied')
for relative in ['install/soccer_perception_ros/lib/python3.8/site-packages/soccer_perception',
                 'install/soccer_perception_ros/share/soccer_perception_ros/config']:
    original = project / relative
    if original.exists():
        shutil.copytree(original, backup / relative, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
for item in manifest:
    rel = item['path']; target = project / rel
    if target.exists():
        saved = backup / 'source' / rel
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, saved)
for item in manifest:
    target = project / item['path']
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(stage / 'files' / item['path'], target)
    if digest(target) != item['sha256']:
        raise RuntimeError('Applied hash mismatch: ' + item['path'])
record = dict(at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              project=str(project), backup=str(backup), engine_sha256=digest(engine),
              weight_sha256=digest(weight), files=manifest,
              git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=str(project), universal_newlines=True).strip(),
              production_started=False, gpu_benchmark_started=False)
(stage / 'applied.json').write_text(json.dumps(record, indent=2) + '\n')
print('Applied %d reviewed files; backup=%s' % (len(manifest), backup))
