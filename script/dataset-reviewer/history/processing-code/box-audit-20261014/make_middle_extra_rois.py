from PIL import Image,ImageDraw
import json
from pathlib import Path
R=Path('dataset_processing/box-audit-20261014');rows=json.load(open(R/'middle-missing-extra-inventory.json'));tiles=[];mapping=[]
for r in rows:
 i=r['index'];roi=[0,315,100,376]
 if i in (5718,5719,5720,5721):roi=[0,315,140,376]
 if i in (5722,5723):roi=[240,245,345,310]
 if 5724<=i<=5729:roi=[200,310,300,376]
 if 5730<=i<=5733:roi=[215,330,325,376]
 if 5734<=i<=5737:roi=[200,310,350,376]
 im=Image.open(r['image_path']).convert('RGB');c=im.crop(roi);sc=min(295/c.width,205/c.height);c=c.resize((round(c.width*sc),round(c.height*sc)),Image.Resampling.NEAREST);dd=ImageDraw.Draw(c)
 for x in range((roi[0]//10+1)*10,roi[2],10):dd.line(((x-roi[0])*sc,0,(x-roi[0])*sc,5),fill='yellow');dd.text(((x-roi[0])*sc,6),str(x),fill='yellow')
 for y in range((roi[1]//10+1)*10,roi[3],10):dd.line((0,(y-roi[1])*sc,6,(y-roi[1])*sc),fill='yellow');dd.text((7,(y-roi[1])*sc),str(y),fill='yellow')
 t=Image.new('RGB',(300,240),'#202020');t.paste(c,(0,35));d=ImageDraw.Draw(t);d.text((3,1),f"{i} f{r['source_frame_idx']} {r['eye']}",fill='white');d.text((3,17),f'roi {roi} scale{sc:.3f}',fill='white');tiles.append(t);mapping.append({'index':i,'roi':roi,'scale':sc})
for st in range(0,len(tiles),12):
 o=Image.new('RGB',(1200,720),'#202020')
 for j,t in enumerate(tiles[st:st+12]):o.paste(t,(j%4*300,j//4*240))
 o.save(R/f'middle-extra-native-roi-{st//12+1:02}.png')
(R/'middle-extra-native-roi-map.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2))
