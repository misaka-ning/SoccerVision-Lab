#!/usr/bin/env python3
"""Audit-only pretrained global features; no detector training or source writes."""
import hashlib,json,os,time
from pathlib import Path
import numpy as np
from PIL import Image
import torch
from torchvision.models import mobilenet_v3_small

ROOT=Path(__file__).resolve().parents[1]
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
torch.manual_seed(20261019)
started=time.time()
inventory=json.loads((ROOT/'data/inventory.json').read_text())
rows=[r for r in inventory if r['usable']]
weight=ROOT/'models/mobilenet_v3_small-047dcff4.pth'
sha=hashlib.sha256(weight.read_bytes()).hexdigest()
assert sha.startswith('047dcff4'), 'Official checkpoint hash prefix mismatch'
model=mobilenet_v3_small(weights=None)
model.load_state_dict(torch.load(weight,map_location='cpu',weights_only=True))
model.eval()
mean=np.array([.485,.456,.406],dtype=np.float32)[None,:,None,None]
std=np.array([.229,.224,.225],dtype=np.float32)[None,:,None,None]
all_features=[]
with torch.inference_mode():
    for start in range(0,len(rows),32):
        ims=[]
        for row in rows[start:start+32]:
            with Image.open(row['image_path']) as im:
                ims.append(np.asarray(im.convert('RGB').resize((224,224),Image.Resampling.BILINEAR),dtype=np.float32).transpose(2,0,1)/255.)
        batch=torch.from_numpy((np.stack(ims)-mean)/std)
        f=model.features(batch).mean((2,3))
        f=torch.nn.functional.normalize(f,p=2,dim=1)
        all_features.append(f.numpy())
        if start%1024==0: print(json.dumps(dict(done=min(start+32,len(rows)),total=len(rows),seconds=round(time.time()-started,1))),flush=True)
features=np.concatenate(all_features).astype(np.float32)
assert features.shape==(8148,576) and np.all(np.isfinite(features))
assert np.allclose(np.linalg.norm(features,axis=1),1,atol=1e-5)
np.savez_compressed(ROOT/'data/embeddings.npz',features=features,indices=np.array([r['index'] for r in rows],dtype=np.int32))
meta=dict(executed=True,model='torchvision.mobilenet_v3_small',weights='IMAGENET1K_V1',
          pretrained=True,checkpoint_url='https://download.pytorch.org/models/mobilenet_v3_small-047dcff4.pth',
          checkpoint_sha256=sha,torch_version=torch.__version__,
          torchvision_version=__import__('torchvision').__version__,dimension=576,
          pooling='mean of final backbone feature map H,W, before classifier',normalization='L2',
          preprocess=dict(color='RGB',resize=[224,224],interpolation='Pillow BILINEAR',
                          crop='none; whole-frame anisotropic resize to preserve all edge content',scale='divide 255',
                          mean=[.485,.456,.406],std=[.229,.224,.225]),
          batch_size=32,device='CPU',threads=1,seed=20261019,images=len(rows),elapsed_seconds=time.time()-started,
          limitation='ImageNet classification backbone, not DINOv2. Whole-frame warp differs from official center-crop evaluation. Similarity is candidate evidence, not proof of event identity or leakage.',
          faiss_used=False,retrieval='exact cross-split normalized inner product in bounded NumPy batches; no within-train all-pairs',
          source_inventory_sha256=hashlib.sha256((ROOT/'data/inventory.json').read_bytes()).hexdigest(),
          source_files_written=False)
(ROOT/'data/embedding-model.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(meta),flush=True)
