#!/usr/bin/env python3
"""Propose image-edge-based football boxes. Never changes production labels.

A circular/elliptical boundary search tests actual Lab colour changes around many
candidate outlines. A local detector may provide semantic cross-checks elsewhere;
this module alone never confirms ball presence. Fits are review hypotheses, not GT.
Large motions, weak boundaries, blur, clipping and occlusion remain explicit flags.
"""
import argparse, hashlib, json, math, time
from pathlib import Path
import cv2
import numpy as np

ROOT = Path('/home/misaka/workspace/dataset_processing/box-audit-20261014').resolve()

def protected_output(path):
    p = Path(path).resolve()
    if not p.is_relative_to(ROOT):
        raise ValueError('Outputs must remain in ' + str(ROOT))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def iou(a,b):
    x=max(0,min(a[2],b[2])-max(a[0],b[0])); y=max(0,min(a[3],b[3])-max(a[1],b[1]))
    inter=x*y
    return inter/max(1e-8,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)

def ellipse_search(image, box):
    """Return the best external-boundary hypothesis and measurable evidence."""
    H,W=image.shape[:2]; x1,y1,x2,y2=map(float,box); bw=x2-x1; bh=y2-y1
    if min(bw,bh)<=3:
        return {'xyxy':list(box),'fit_confidence':0.0,'flags':['too_few_source_pixels'], 'evidence':{}}
    pad=max(12,max(bw,bh)*.8)
    ox=max(0,int(x1-pad)); oy=max(0,int(y1-pad)); ex=min(W,int(math.ceil(x2+pad))); ey=min(H,int(math.ceil(y2+pad)))
    crop=image[oy:ey,ox:ex]
    scale=min(2.,240/max(crop.shape[:2]))
    if scale!=1: crop=cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_LINEAR)
    ch,cw=crop.shape[:2]
    lab=cv2.cvtColor(crop,cv2.COLOR_BGR2LAB).astype(np.float32)
    lab=cv2.GaussianBlur(lab,(0,0),.7)
    # L* and two colour channels contribute, so multi-colour panels need no seed colour.
    gx=cv2.Sobel(lab,cv2.CV_32F,1,0,ksize=3)/8
    gy=cv2.Sobel(lab,cv2.CV_32F,0,1,ksize=3)/8
    gradient=np.sqrt((gx*gx+gy*gy).sum(axis=2))
    unit=max(5.,float(np.percentile(gradient,85)))
    cx0=((x1+x2)/2-ox)*scale; cy0=((y1+y2)/2-oy)*scale
    side=max(bw,bh)*scale
    theta=np.linspace(0,2*np.pi,96,endpoint=False,dtype=np.float32); ux=np.cos(theta); uy=np.sin(theta)
    base_aspect=np.clip(bw/bh,.7,1.4)
    aspects=np.unique(np.round([.83,.92,1.,1.08,1.2,base_aspect],3))
    centers_x=cx0+np.linspace(-.28,.28,9)*side
    centers_y=cy0+np.linspace(-.28,.28,9)*side
    radii=np.linspace(.38,.76,24)*side
    ccx,ccy,rr,aa=np.meshgrid(centers_x,centers_y,radii,aspects,indexing='ij')
    params=np.stack([ccx.ravel(),ccy.ravel(),rr.ravel(),aa.ravel()],axis=1).astype(np.float32)
    # Radius is geometric mean; aspect scales the two axes by reciprocal sqrt.
    def score_batch(p):
        cx,cy,r,aspect=p.T; rx=r*np.sqrt(aspect); ry=r/np.sqrt(aspect)
        px=cx[:,None]+rx[:,None]*ux; py=cy[:,None]+ry[:,None]*uy
        delta=np.clip(r*.07,1.2,4.5)[:,None]
        ix=px-delta*ux; iy=py-delta*uy; ax=px+delta*ux; ay=py+delta*uy
        valid=(ix>=1)&(iy>=1)&(ax<cw-1)&(ay<ch-1)&(ax>=1)&(ay>=1)&(ix<cw-1)&(iy<ch-1)
        inn=cv2.remap(lab,ix.astype(np.float32),iy.astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        outer=cv2.remap(lab,ax.astype(np.float32),ay.astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        edge=np.sqrt(((inn-outer)**2).sum(axis=2))/(unit*max(1.,2.5))
        edge=np.minimum(edge,2.5)*valid
        cover=((edge>.55)&valid).sum(axis=1)/np.maximum(1,valid.sum(axis=1))
        # Four quadrant support is difficult for a pentagon panel or a straight leg edge to imitate.
        sides=np.stack([np.mean(edge[:,k:k+24],axis=1) for k in (0,24,48,72)],axis=1)
        balanced=np.sort(sides,axis=1)[:,0:3].mean(axis=1)
        edge_mean=np.minimum(edge,1.5).sum(axis=1)/np.maximum(1,valid.sum(axis=1))
        # Interior pattern can have strong edges; exterior should usually be more homogeneous.
        bx=cx[:,None]+(rx[:,None]+delta*2.4)*ux; by=cy[:,None]+(ry[:,None]+delta*2.4)*uy
        far=cv2.remap(lab,bx.astype(np.float32),by.astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        exterior=np.sqrt(((far-outer)**2).sum(axis=2))/(unit*2.5)
        smooth=np.mean(np.minimum(exterior,1.5)*valid,axis=1)
        # Mild centre and size priors break ambiguous ties; no fixed proportional shrink.
        prior=((cx-cx0)**2+(cy-cy0)**2)/(side*side)
        score=(.55*edge_mean+.3*balanced+.35*cover-.33*smooth-.35*prior)
        score*=np.minimum(1.,valid.mean(axis=1)/.85)
        return score,cover,edge_mean,balanced,smooth,valid.mean(axis=1)
    all_scores=[]; stats=[]
    for start in range(0,len(params),512):
        s=score_batch(params[start:start+512]); all_scores.append(s[0]); stats.append(np.stack(s[1:],axis=1))
    scores=np.concatenate(all_scores); evidence=np.concatenate(stats); order=np.argsort(scores)[::-1]
    best=params[order[0]]; sc=float(scores[order[0]])
    # A second local stage increases precision without changing the image information.
    cx,cy,r,aspect=best
    dx=np.linspace(-.035,.035,7)*side; dr=np.linspace(-.035,.035,9)*side
    ccx,ccy,rr,aa=np.meshgrid(cx+dx,cy+dx,r+dr,[aspect],indexing='ij')
    fine=np.stack([ccx.ravel(),ccy.ravel(),rr.ravel(),aa.ravel()],axis=1).astype(np.float32)
    fs=score_batch(fine); k=int(np.argmax(fs[0])); best=fine[k]; sc=float(fs[0][k]); ev=np.array([x[k] for x in fs[1:]])
    cx,cy,r,aspect=map(float,best); rx=r*math.sqrt(aspect)/scale; ry=r/math.sqrt(aspect)/scale; cx=cx/scale+ox; cy=cy/scale+oy
    candidate=[max(0,cx-rx),max(0,cy-ry),min(W,cx+rx),min(H,cy+ry)]
    # This confidence quantifies image boundary support only; it is never ball class confidence.
    coverage,edge_mean,balanced,smooth,valid=map(float,ev)
    confidence=float(np.clip((coverage-.35)/.5,0,1)*np.clip(balanced/.7,0,1)*np.clip(sc/.9,0,1))
    flags=[]
    if coverage<.65 or balanced<.45: flags.append('weak_or_partial_external_boundary')
    if valid<.94: flags.append('image_edge_clipped')
    if min(bw,bh)<32: flags.append('small_source_object'); confidence=min(confidence,.4)
    area=(candidate[2]-candidate[0])*(candidate[3]-candidate[1]); oldarea=bw*bh
    if area/oldarea<.62: flags.append('large_shrink_requires_visual_review'); confidence=min(confidence,.35)
    if area/oldarea>1.4: flags.append('original_box_may_cover_only_part_of_ball'); confidence=min(confidence,.35)
    if iou(candidate,box)<.55: flags.append('large_motion_or_size_change'); confidence=min(confidence,.3)
    gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY); sharp=float(cv2.Laplacian(gray,cv2.CV_32F).var())
    if sharp<70: flags.append('blur_or_low_texture')
    # Competing distinct outlines tell the reviewer the solution is ambiguous.
    alternatives=[]
    for idx in order[1:]:
        pcx,pcy,pr,pa=map(float,params[idx]); prx=pr*math.sqrt(pa)/scale; pry=pr/math.sqrt(pa)/scale
        b=[max(0,pcx/scale+ox-prx),max(0,pcy/scale+oy-pry),min(W,pcx/scale+ox+prx),min(H,pcy/scale+oy+pry)]
        if iou(candidate,b)<.65:
            alternatives.append({'xyxy':[round(v,3) for v in b],'score':round(float(scores[idx]),4)})
            break
    if alternatives and alternatives[0]['score']>sc*.92:
        flags.append('competing_outline_hypotheses'); confidence*=.55
    return {'xyxy':[round(v,3) for v in candidate], 'fit_confidence':round(confidence,4),'flags':flags,
            'evidence':{'method':'lab_external_ellipse_boundary_v2','score':round(sc,4), 'angular_coverage':round(coverage,4),
                        'balanced_quadrant_support':round(balanced,4),'edge_strength':round(edge_mean,4),
                        'exterior_change':round(smooth,4),'valid_perimeter_fraction':round(valid,4),
                        'area_ratio':round(area/oldarea,4),'iou_with_original':round(iou(candidate,box),4),
                        'crop_laplacian_variance':round(sharp,3)},'alternatives':alternatives}

def refine_one(image,row):
    old=row['xyxy']; out=ellipse_search(image,old)
    metadata=row.get('metadata',row.get('meta',{})); status=row.get('annotation_status',row.get('status',metadata.get('annotation_status','')))
    if metadata.get('Occluded') in ('1',1,True): out['flags'].append('occluded_visible_extent_requires_manual_review'); out['fit_confidence']*=.5
    if metadata.get('Blurred') in ('1',1,True): out['flags'].append('metadata_blurred'); out['fit_confidence']=min(out['fit_confidence']*.7,.35)
    human=status in ('reviewed_annotation','provided_annotation')
    out.update({'original_xyxy':[round(float(v),3) for v in old],'filename':row['filename'], 'box_index':row.get('box_index',0),
                'annotation_status_before':status,'is_human_provided_annotation':human,
                'proposal_status':'pending_visual_review','automatically_approved':False,
                'candidate_type':'ellipse_boundary_hypothesis','ball_presence_confirmed':False})
    if human: out['flags'].append('human_annotation_change_proposal_only')
    if out['fit_confidence']<.45: out['recommendation']='retain_original_pending_manual_review'
    else: out['recommendation']='inspect_external_boundary_candidate'
    return out

def montage(rows,output):
    thumbs=[]; mappings=[]
    for sequence,row in enumerate(rows):
        im=cv2.imread(row['image_path']); old=row['original_xyxy']; new=row['xyxy']; x1,y1,x2,y2=old
        pad=max(15,max(x2-x1,y2-y1)*.45); xx=max(0,int(min(x1,new[0])-pad)); yy=max(0,int(min(y1,new[1])-pad)); ex=min(im.shape[1],int(max(x2,new[2])+pad)); ey=min(im.shape[0],int(max(y2,new[3])+pad)); crop=im[yy:ey,xx:ex].copy()
        scale=min(215/crop.shape[1],175/crop.shape[0]); crop=cv2.resize(crop,None,fx=scale,fy=scale)
        for b,col in [(old,(0,0,255)),(new,(0,220,0))]:
            cv2.rectangle(crop,(int((b[0]-xx)*scale),int((b[1]-yy)*scale)),(int((b[2]-xx)*scale),int((b[3]-yy)*scale)),col,1)
        t=np.full((210,225,3),245,np.uint8); t[:crop.shape[0],:crop.shape[1]]=crop
        mappings.append({'sheet':sequence//24,'tile':sequence%24,'inventory_box_index':row.get('inventory_box_index'), 'filename':row['filename'],'box_index':row['box_index'], 'original_xyxy':old,'candidate_xyxy':new,'crop_xyxy':[xx,yy,ex,ey], 'fit_confidence':row['fit_confidence']})
        cv2.putText(t,str(row.get('inventory_box_index',''))+' '+row['filename'][-27:],(3,188),cv2.FONT_HERSHEY_SIMPLEX,.31,(0,0,0),1)
        cv2.putText(t,f"fit {row['fit_confidence']:.2f} coverage {row['evidence'].get('angular_coverage',0):.2f}",(3,204),cv2.FONT_HERSHEY_SIMPLEX,.35,(0,0,0),1); thumbs.append(t)
    for start in range(0,len(thumbs),24):
        ts=thumbs[start:start+24]; canvas=np.full((210*((len(ts)+5)//6),225*6,3),255,np.uint8)
        for j,t in enumerate(ts): canvas[(j//6)*210:(j//6+1)*210,(j%6)*225:(j%6+1)*225]=t
        cv2.imwrite(str(protected_output(output.with_name(output.stem+f'-{start//24}.jpg'))),canvas)
    protected_output(output.with_name(output.stem+'-map.json')).write_text(json.dumps(mappings,ensure_ascii=False,indent=2)+'\n')

def normalize_rows(raw):
    rows=raw if isinstance(raw,list) else raw.get('boxes',raw.get('rows',raw.get('images')))
    flattened=[]
    for row in rows:
        if row.get('xyxy') is not None:
            flattened.append(row)
        else:
            for box_index,box in enumerate(row.get('boxes',[])):
                flattened.append({'image_path':row['image_path'],'filename':row['filename'],
                    'metadata':row.get('meta',row.get('metadata',{})), 'box_index':box_index,
                    'original_label_line':box.get('line',box_index+1),'xyxy':box['xyxy'],
                    'label_sha256':row.get('label_sha256'),'image_sha256':row.get('image_sha256')})
    return flattened

class CropDetector:
    def __init__(self,model):
        self.net=cv2.dnn.readNetFromONNX(str(model))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self.path=str(Path(model).resolve())
    def predict(self,image,box):
        h,w=image.shape[:2]; x1,y1,x2,y2=map(float,box); pad=max(20,max(x2-x1,y2-y1))
        ox=max(0,int(x1-pad)); oy=max(0,int(y1-pad)); crop=image[oy:min(h,int(y2+pad)),ox:min(w,int(x2+pad))]
        ch,cw=crop.shape[:2]; size=640; ratio=size/max(ch,cw); rw,rh=round(cw*ratio),round(ch*ratio)
        left,top=(size-rw)//2,(size-rh)//2; padded=np.full((size,size,3),114,np.uint8)
        padded[top:top+rh,left:left+rw]=cv2.resize(crop,(rw,rh))
        self.net.setInput(cv2.dnn.blobFromImage(padded,1/255.,(size,size),swapRB=True,crop=False))
        prediction=np.squeeze(self.net.forward()); prediction=prediction.T if prediction.shape[0]<prediction.shape[1] else prediction
        if prediction.shape[1]!=5: raise ValueError('Crop detector must be verified one-class ball ONNX [cx,cy,w,h,score]')
        boxes=[]; scores=[]
        for cx,cy,bw,bh,confidence in prediction:
            if confidence<.05: continue
            a=max(0,min(cw,(float(cx)-float(bw)/2-left)/ratio)); b=max(0,min(ch,(float(cy)-float(bh)/2-top)/ratio))
            c=max(0,min(cw,(float(cx)+float(bw)/2-left)/ratio)); d=max(0,min(ch,(float(cy)+float(bh)/2-top)/ratio))
            if c>a and d>b: boxes.append([a,b,c-a,d-b]); scores.append(float(confidence))
        keep=np.asarray(cv2.dnn.NMSBoxes(boxes,scores,.05,.5)).reshape(-1); result=[]
        for k in keep:
            a,b,bw,bh=boxes[int(k)]; result.append({'xyxy':[round(a+ox,3),round(b+oy,3),round(a+bw+ox,3),round(b+bh+oy,3)],
                'model_confidence':round(scores[int(k)],6),'source':'local_crop_onnx_640','model_path':self.path,
                'proposal_status':'pending_visual_review'})
        return result

def dump(path,value):
    p=protected_output(path); tmp=p.with_suffix(p.suffix+'.tmp'); tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n'); tmp.replace(p)

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--input',required=True,type=Path); ap.add_argument('--output',required=True,type=Path); ap.add_argument('--montage',type=Path); ap.add_argument('--limit',type=int); ap.add_argument('--start',type=int,default=0); ap.add_argument('--threads',type=int,default=2); ap.add_argument('--crop-model',type=Path); ap.add_argument('--save-every',type=int,default=100); args=ap.parse_args(); cv2.setNumThreads(args.threads)
    rows=normalize_rows(json.loads(args.input.read_text()))[args.start:]
    if args.limit: rows=rows[:args.limit]
    detector=CropDetector(args.crop_model) if args.crop_model else None
    result=[]; errors=[]; started=time.monotonic(); previous_path=None; image=None
    summary_path=args.output.with_name(args.output.stem+'-summary.json')
    def save(complete=False):
        dump(args.output,result)
        dump(summary_path,{'schema_version':2,'algorithm':'lab_external_ellipse_boundary_v2', 'input_path':str(args.input.resolve()),
            'input_sha256':hashlib.sha256(args.input.read_bytes()).hexdigest(),'boxes_expected':len(rows),'boxes_completed':len(result),
            'errors':errors,'elapsed_seconds':round(time.monotonic()-started,2),'complete':complete,
            'all_pending_visual_review':True,'automatically_approved_count':0,'no_detection_means':'unknown_not_no_ball',
            'crop_model':str(args.crop_model) if args.crop_model else None})
    for i,row in enumerate(rows):
        try:
            if row['image_path']!=previous_path:
                image=cv2.imread(row['image_path']); previous_path=row['image_path']
            if image is None: raise ValueError('Unreadable '+row['image_path'])
            rr=refine_one(image,row); rr['image_path']=row['image_path']; rr['inventory_box_index']=args.start+i
            rr['original_label_line']=row.get('original_label_line',row.get('box_index',0)+1)
            rr['label_sha256']=row.get('label_sha256'); rr['image_sha256']=row.get('image_sha256')
            if detector:
                detections=detector.predict(image,row['xyxy']); rr['crop_detection_proposals']=detections
                related=[d for d in detections if iou(d['xyxy'],row['xyxy'])>.15]
                if related:
                    match=max(related,key=lambda d:d['model_confidence']*iou(d['xyxy'],row['xyxy']))
                    rr['crop_detector_agreement_iou']=round(iou(rr['xyxy'],match['xyxy']),4)
                    rr['crop_detector_max_related_confidence']=match['model_confidence']
                    if match['model_confidence']>.55 and rr['crop_detector_agreement_iou']<.65:
                        rr['flags'].append('edge_fit_disagrees_with_semantic_crop_detection'); rr['fit_confidence']=min(rr['fit_confidence'],.3)
                    if match['model_confidence']>.55 and iou(row['xyxy'],match['xyxy'])<.5:
                        rr['flags'].append('crop_detector_suggests_original_partial_or_misplaced_box')
                else:
                    rr['flags'].append('no_related_crop_detection_is_not_negative_evidence')
            rr['fit_confidence']=round(rr['fit_confidence'],4)
            if rr['fit_confidence']<.45: rr['recommendation']='retain_original_pending_manual_review'
            result.append(rr)
        except Exception as e:
            errors.append({'filename':row['filename'],'box_index':row.get('box_index'),'error':str(e)})
        if (i+1)%args.save_every==0:
            save(); print(f'refined {i+1}/{len(rows)} ({time.monotonic()-started:.1f}s); errors {len(errors)}',flush=True)
    save(complete=True)
    if args.montage: montage(result,protected_output(args.montage))
    print(f'complete {len(result)} boxes in {time.monotonic()-started:.1f}s',flush=True)
if __name__=='__main__': main()
