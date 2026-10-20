import json,sys,cv2,numpy as np
from pathlib import Path
p=Path('/home/misaka/workspace/dataset_processing/box-audit-20261014');inv=json.loads((p/'inventory.json').read_text());pro={r['index']:r for r in json.loads((p/'middle-corrections-proposals.json').read_text())};out=p/'middle-qa-native';out.mkdir(exist_ok=True)
for i in map(int,sys.argv[1:]):
 r=inv[i];im=cv2.imread(r['image_path']);H,W=im.shape[:2];boxes=pro[i]['boxes_xyxy'];x1=max(0,int(min(b[0] for b in boxes)-35));y1=max(0,int(min(b[1] for b in boxes)-35));x2=min(W,int(max(b[2] for b in boxes)+35));y2=min(H,int(max(b[3] for b in boxes)+35));crop=im[y1:y2,x1:x2];scale=3;crop=cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_NEAREST);gamma=np.uint8(np.clip((crop/255.)**.55*255,0,255));
 for cr in [crop,gamma]:
  for b in boxes:
   a,c,e,f=[int(v) for v in b];cv2.rectangle(cr,((a-x1)*scale,(c-y1)*scale),((e-x1)*scale,(f-y1)*scale),(0,255,0),1)
  for xx in range((x1//10+1)*10,x2,10):cv2.line(cr,((xx-x1)*scale,0),((xx-x1)*scale,cr.shape[0]),(90,90,90),1);cv2.putText(cr,str(xx),((xx-x1)*scale+2,14),cv2.FONT_HERSHEY_SIMPLEX,.35,(0,255,255),1)
  for yy in range((y1//10+1)*10,y2,10):cv2.line(cr,(0,(yy-y1)*scale),(cr.shape[1],(yy-y1)*scale),(90,90,90),1);cv2.putText(cr,str(yy),(2,(yy-y1)*scale+14),cv2.FONT_HERSHEY_SIMPLEX,.35,(0,255,255),1)
 cv2.imwrite(str(out/f'{i}-native.png'),crop);cv2.imwrite(str(out/f'{i}-gamma.png'),gamma)
