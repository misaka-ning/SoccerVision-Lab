import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'): os.environ[k]='1'
try: os.nice(10)
except OSError: pass
import csv,hashlib,io,json,math
from pathlib import Path
from collections import Counter,defaultdict
import numpy as np
import cv2
from PIL import Image,ImageDraw,ImageFont,ImageOps
cv2.setNumThreads(1)
ROOT=Path(__file__).resolve().parents[1]
DATA=Path('/home/misaka/workspace/datasets')
AUDIT=Path('/home/misaka/workspace/dataset_processing/dataset-audit-20261019')
SEED=20261019
FLAGS=['Small','Occluded','Blurred','No Ball']
SOURCE_KEYS={
 'stereo_20261013_104748_922854_7a88b83e76d9406f8ed02e0ded4f36bb':'104748',
 'stereo_20261013_181326_250178_b15c1f6de79441fc9a59436202b7cc5a':'181326',
 'stereo_20261013_181531_750945_d976724b06a247158bb023f3675e05b4_first27min':'181531'}
def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(p,obj):Path(p).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def csvrows(p):
 with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def writecsv(p,records,columns=None):
 columns=columns or list(records[0])
 with Path(p).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');w.writeheader();w.writerows(records)
def stamp(t):
 m,s=divmod(t,60);return f'{int(m):02}:{s:04.1f}'
def preferred_eye(frame):
 return 'left' if hashlib.sha256(f'{SEED}:{frame}'.encode()).digest()[0]%2==0 else 'right'
def representatives(rows):
 groups=defaultdict(list)
 for r in rows:groups[r['frame']].append(r)
 return [next((r for r in groups[f] if r['eye']==preferred_eye(f)),sorted(groups[f],key=lambda r:r['eye'])[0]) for f in sorted(groups)]
def ssim(a,b):
 a=a.astype(np.float32);b=b.astype(np.float32)
 ma=cv2.GaussianBlur(a,(11,11),1.5);mb=cv2.GaussianBlur(b,(11,11),1.5)
 va=cv2.GaussianBlur(a*a,(11,11),1.5)-ma*ma;vb=cv2.GaussianBlur(b*b,(11,11),1.5)-mb*mb
 co=cv2.GaussianBlur(a*b,(11,11),1.5)-ma*mb
 value=((2*ma*mb+6.5025)*(2*co+58.5225))/((ma*ma+mb*mb+6.5025)*(va+vb+58.5225))
 return float(value[5:-5,5:-5].mean())
def font(size=15):
 return ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',size)
def tile(r,w=256,h=144,boxes=True):
 with Image.open(r['source_image']) as im:im=im.convert('RGB').resize((w,h),Image.Resampling.BILINEAR)
 if boxes:
  d=ImageDraw.Draw(im)
  for box in r['boxes']:
   x,y,bw,bh=box[1:];d.rectangle(((x-bw/2)*w,(y-bh/2)*h,(x+bw/2)*w,(y+bh/2)*h),outline='#00ff66',width=2)
 return im
def contact(rows,path,title,cols=5,tile_w=256,tile_h=144):
 per_h=tile_h+45;canvas=Image.new('RGB',(cols*tile_w,42+math.ceil(len(rows)/cols)*per_h),'#f2f4f7');d=ImageDraw.Draw(canvas)
 d.text((10,9),title,fill='#14202e',font=font(18))
 for n,r in enumerate(rows):
  x=n%cols*tile_w;y=42+n//cols*per_h
  canvas.paste(tile(r,tile_w,tile_h),(x,y))
  label=(r.get('display_role','')+' '+stamp(r['seconds'])+' '+r['eye']+' '+str(r['frame'])) if r['seconds'] is not None else r['filename']
  d.text((x+4,y+tile_h+2),label,fill='#14202e',font=font(13))
  d.text((x+4,y+tile_h+21),' '.join(f for f in FLAGS if r['flags'][f]),fill='#9c4810',font=font(13))
 canvas.save(path)
 return dict(path=str(Path(path).relative_to(ROOT)),images=[r['filename'] for r in rows],sha256=sha(path))
