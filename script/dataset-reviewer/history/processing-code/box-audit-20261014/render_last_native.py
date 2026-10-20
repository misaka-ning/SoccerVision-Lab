import sys,json,cv2
from pathlib import Path
p=Path('/home/misaka/workspace/dataset_processing/box-audit-20261014'); r=json.loads((p/'inventory.json').read_text());out=p/'last-native';out.mkdir(exist_ok=True)
for idx in map(int,sys.argv[1:]):
 row=r[idx]; im=cv2.imread(row['image_path']);H,W=im.shape[:2]
 for b in row['boxes']:
  a,c,e,f=map(int,b['xyxy']);cv2.rectangle(im,(a,c),(e,f),(0,180,255),1)
 for xx in range(0,W,50):cv2.line(im,(xx,0),(xx,H),(130,130,130),1);cv2.putText(im,str(xx),(xx+2,15),cv2.FONT_HERSHEY_SIMPLEX,.35,(0,255,0),1)
 for yy in range(0,H,50):cv2.line(im,(0,yy),(W,yy),(130,130,130),1);cv2.putText(im,str(yy),(2,yy+12),cv2.FONT_HERSHEY_SIMPLEX,.35,(0,255,0),1)
 cv2.imwrite(str(out/f'{idx}.jpg'),im);print(idx,row['filename'],[b['xyxy'] for b in row['boxes']])
