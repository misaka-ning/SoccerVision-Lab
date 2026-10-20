import concurrent.futures
import json
from pathlib import Path
import cv2
import numpy as np

W=Path(__file__).resolve().parent
ROWS=[r for r in json.loads((W/'inventory.json').read_text()) if r['filename'].startswith('video_4bec9c343db72928_')]
cv2.setNumThreads(1)

def letterbox(image,width,height):
    ih,iw=image.shape[:2];s=min(width/iw,height/ih)
    nw,nh=max(1,round(iw*s)),max(1,round(ih*s))
    result=np.zeros((height,width,3),np.uint8)
    thumb=cv2.resize(image,(nw,nh),interpolation=cv2.INTER_AREA if s<1 else cv2.INTER_NEAREST)
    x,y=(width-nw)//2,(height-nh)//2;result[y:y+nh,x:x+nw]=thumb
    return result

def scene_page(task):
    group,page,rows=task
    canvas=np.zeros((8*210,6*320,3),np.uint8)
    for i,r in enumerate(rows):
        image=cv2.imread(r['image_path'])
        color=(0,210,0) if r['meta']['annotation_status'] in ['reviewed_annotation','provided_annotation'] else (0,165,255)
        for b in r['boxes']:
            coords=[round(v) for v in b['xyxy']]
            cv2.rectangle(image,tuple(coords[:2]),tuple(coords[2:]),color,2)
        tile=np.zeros((210,320,3),np.uint8);tile[:180]=letterbox(image,320,180)
        short=r['filename'].replace('video_4bec9c343db72928_frame_','').replace('.png','')
        cv2.putText(tile,f'{r["index"]} {short} B={len(r["boxes"])}',(5,198),cv2.FONT_HERSHEY_SIMPLEX,.44,(255,255,255),1)
        y,x=divmod(i,6);canvas[y*210:(y+1)*210,x*320:(x+1)*320]=tile
    dest=W/'review-new'/group/'scene'/f'page-{page:03d}.jpg';dest.parent.mkdir(parents=True,exist_ok=True)
    cv2.imwrite(str(dest),canvas,[cv2.IMWRITE_JPEG_QUALITY,95])
    return {'group':group,'kind':'scene','page':page,'path':str(dest),'filenames':[r['filename'] for r in rows],'indices':[r['index'] for r in rows]}

def roi_page(task):
    group,page,items=task
    canvas=np.zeros((5*256,6*256,3),np.uint8)
    for i,(r,bidx) in enumerate(items):
        image=cv2.imread(r['image_path']);box=r['boxes'][bidx]['xyxy'];bw,bh=box[2]-box[0],box[3]-box[1]
        pad=max(12,max(bw,bh)*.55)
        x1,y1=max(0,int(box[0]-pad)),max(0,int(box[1]-pad));x2,y2=min(r['width'],int(box[2]+pad+1)),min(r['height'],int(box[3]+pad+1))
        crop=image[y1:y2,x1:x2].copy()
        if not crop.size:continue
        color=(0,210,0) if r['meta']['annotation_status'] in ['reviewed_annotation','provided_annotation'] else (0,165,255)
        coords=[round(box[0]-x1),round(box[1]-y1),round(box[2]-x1),round(box[3]-y1)]
        cv2.rectangle(crop,tuple(coords[:2]),tuple(coords[2:]),color,1)
        tile=np.zeros((256,256,3),np.uint8);tile[28:]=letterbox(crop,256,228)
        short=r['filename'].replace('video_4bec9c343db72928_frame_','').replace('.png','')
        cv2.putText(tile,f'{r["index"]} {short} #{bidx}',(3,18),cv2.FONT_HERSHEY_SIMPLEX,.42,(255,255,255),1)
        y,x=divmod(i,6);canvas[y*256:(y+1)*256,x*256:(x+1)*256]=tile
    dest=W/'review-new'/group/'roi'/f'page-{page:03d}.jpg';dest.parent.mkdir(parents=True,exist_ok=True)
    cv2.imwrite(str(dest),canvas,[cv2.IMWRITE_JPEG_QUALITY,95])
    return {'group':group,'kind':'roi','page':page,'path':str(dest),'items':[{'filename':r['filename'],'index':r['index'],'box_index':bi} for r,bi in items]}

tasks=[];groups={}
for g,name in enumerate(['first','middle','last']):
    subset=ROWS[g*2146:(g+1)*2146];groups[name]={'images':len(subset),'indices':[r['index'] for r in subset]}
    tasks.extend((scene_page,(name,k//48,subset[k:k+48])) for k in range(0,len(subset),48))
    boxes=[(r,bi) for r in subset for bi in range(len(r['boxes']))]
    tasks.extend((roi_page,(name,k//30,boxes[k:k+30])) for k in range(0,len(boxes),30))
results=[]
def execute(task):fn,args=task;return fn(args)
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    for i,result in enumerate(pool.map(execute,tasks),1):
        results.append(result)
        if i%20==0:print(f'contact pages {i}/{len(tasks)}',flush=True)
index={'groups':groups,'pages':results,'note':'Current existing boxes only. Full images plus original-box crops; inspect native pixels for uncertain boundaries.'}
(W/'review-new/index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'new_images':len(ROWS),'pages':len(results),'groups':groups.keys()},default=list))
