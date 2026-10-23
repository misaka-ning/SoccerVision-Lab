"""Read-only finished-run recovery archive with independent per-file hashes."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
root=Path('/home/nvidia/soccer_backend_tensorrt/results/E04_tensorrt_pipeline/preprocess_race/20261023T014627Z')
attempt=Path((root/'CURRENT').read_text().strip()).resolve()
if attempt.parent!=root.resolve():raise RuntimeError('Unexpected CURRENT path')
state=json.loads((attempt/'status.json').read_text())
if state['status'] not in ('complete','failed'):raise RuntimeError('Run is not finished')
files=[p for p in attempt.rglob('*') if p.is_file()]
files += [Path(str(attempt)+'.log'),root/'CURRENT',root/'PID',root/'payload_manifest.json',root/'frozen.json']
manifest={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as tar:
 for path in files:tar.add(str(path),arcname=str(path.relative_to(root)),recursive=False)
 data=json.dumps(manifest,indent=2).encode();info=tarfile.TarInfo('recovery_sha256.json');info.size=len(data);tar.addfile(info,io.BytesIO(data))
