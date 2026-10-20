import json,sys,importlib.util
from pathlib import Path
import cv2,numpy as np
W=Path(__file__).parent
sp=importlib.util.spec_from_file_location('det','/tmp/football-detector-181531/run_detector.py');det=importlib.util.module_from_spec(sp);sp.loader.exec_module(det)
cv2.setNumThreads(3);net=cv2.dnn.readNetFromONNX('/home/misaka/.local/share/vision-studio/converted-models/best-640.onnx')
ids={idx for p in json.loads((W/'middle-native-index.json').read_text()) for idx in p['indices']};rows=[x for x in json.loads((W/'inventory.json').read_text()) if x['index'] in ids];out={}
for x in rows:
 im=cv2.imread(x['image_path']);a=det.onnx_predict(net,im,640,.025,.4,cv2,np)
 # additional native bottom and center crops recover balls overlooked by full-frame detector
 for ox,oy,ex,ey in [(0,160,im.shape[1],im.shape[0]),(0,0,im.shape[1]//2,im.shape[0]),(im.shape[1]//2,0,im.shape[1],im.shape[0])]:
  for b in det.onnx_predict(net,im[oy:ey,ox:ex],640,.04,.4,cv2,np):
   b['xyxy']=[b['xyxy'][0]+ox,b['xyxy'][1]+oy,b['xyxy'][2]+ox,b['xyxy'][3]+oy];b['source']='native_crop_onnx';a.append(b)
 out[x['filename']]=a
(W/'middle-model.json').write_text(json.dumps(out,indent=2));print('completed',len(rows))
