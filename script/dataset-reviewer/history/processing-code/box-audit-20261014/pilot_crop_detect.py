import sys,json,cv2,numpy as np,time
from pathlib import Path
sys.path.insert(0,'/tmp/football-detector-181531'); from run_detector import onnx_predict
cv2.setNumThreads(2)
p=Path('/home/misaka/workspace/dataset_processing/box-audit-20261014'); rows=json.loads((p/'pilot-boxes.json').read_text()); net=cv2.dnn.readNetFromONNX('/home/misaka/.local/share/vision-studio/converted-models/best-640.onnx'); out=[]; t=time.monotonic()
for i,r in enumerate(rows):
 im=cv2.imread(r['image_path']); h,w=im.shape[:2]; x1,y1,x2,y2=r['xyxy']; pad=max(20,max(x2-x1,y2-y1)*1.); ox=max(0,int(x1-pad)); oy=max(0,int(y1-pad)); crop=im[oy:min(h,int(y2+pad)),ox:min(w,int(x2+pad))]
 boxes=onnx_predict(net,crop,640,.05,.5,cv2,np)
 for b in boxes: b['xyxy']=[b['xyxy'][0]+ox,b['xyxy'][1]+oy,b['xyxy'][2]+ox,b['xyxy'][3]+oy]
 out.append({**r,'crop_detections':boxes})
 if i%20==0:print(i,round(time.monotonic()-t,1),flush=True)
(p/'pilot-crop-detections.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
