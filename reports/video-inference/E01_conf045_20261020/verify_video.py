#!/usr/bin/env python3
"""Decode both complete outputs and verify alignment, settings, and render samples."""
from pathlib import Path
import json
import cv2
import numpy as np
from PIL import Image, ImageDraw

out=Path(__file__).resolve().parent
manifest=json.loads((out/'manifest.json').read_text())
fps=manifest['encoding']['fps']
width,height=manifest['encoding']['width'],manifest['encoding']['height']
rows=[json.loads(line) for line in (out/'predictions.jsonl').read_text().splitlines()]
assert len(rows)==2700
for index,row in enumerate(rows):
    assert row['output_frame']==index and row['output_time_seconds']==index/fps
    clip=manifest['clips'][row['clip']-1]
    expected=clip['source_first_frame']+index-round(clip['output_start_seconds']*fps)
    assert row['source_frame']==expected
    assert row['source_time_seconds']==expected/fps
    for detection in row['detections']:
        assert detection['confidence']>=0.45 and detection['class_id']==0
        eye_offset=0 if detection['eye']=='left' else width//2
        eye=detection['xyxy_eye']; video=detection['xyxy_video']
        assert np.allclose(video,[eye[0]+eye_offset,eye[1],eye[2]+eye_offset,eye[3]])
indices=set()
for clip in manifest['clips']:
    start=round(clip['output_start_seconds']*fps)
    end=round(clip['output_end_seconds']*fps)
    indices.update([start,(start+end)//2,end-1])
images={}
video_checks={}
for tag,info in manifest['outputs'].items():
    cap=cv2.VideoCapture(info['path'])
    assert cap.isOpened()
    header={'width':int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), 'height':int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            'fps':cap.get(cv2.CAP_PROP_FPS),'header_frames':int(cap.get(cv2.CAP_PROP_FRAME_COUNT))}
    assert header==dict(width=width,height=height,fps=float(fps),header_frames=2700)
    frames=0
    snapshots={}
    while True:
        ok,frame=cap.read()
        if not ok:break
        assert frame.shape==(height,width,3)
        if frames in indices:snapshots[frames]=frame
        frames+=1
    cap.release()
    assert frames==2700 and len(snapshots)==len(indices)
    images[tag]=snapshots
    video_checks[tag]={**header,'decoded_frames':frames,'duration_seconds':frames/fps,'full_decode_passed':True}
source=cv2.VideoCapture(manifest['source']['path'])
psnr=[]
for index in sorted(indices):
    source.set(cv2.CAP_PROP_POS_FRAMES,rows[index]['source_frame'])
    ok,original=source.read();assert ok
    encoded=images['original_montage'][index]
    error=float(np.mean((original.astype(np.float32)-encoded.astype(np.float32))**2))
    value=10*np.log10(255**2/error) if error else 100
    assert value>30, (index,value)
    psnr.append(float(value))
source.release()
canvas=Image.new('RGB',(1344,len(manifest['clips'])*216),(20,20,20))
draw=ImageDraw.Draw(canvas)
for rownum,clip in enumerate(manifest['clips']):
    index=(round(clip['output_start_seconds']*fps)+round(clip['output_end_seconds']*fps))//2
    y=rownum*216
    for col,tag in enumerate(('original_montage','E01_conf045_boxes')):
        im=Image.fromarray(cv2.cvtColor(images[tag][index],cv2.COLOR_BGR2RGB))
        im=im.resize((672,188),Image.Resampling.LANCZOS)
        canvas.paste(im,(col*672,y+27))
        draw.text((col*672+8,y+7),f"Clip {clip['clip']} | source {clip['source_start']}-{clip['source_end']} | {'Original' if col==0 else 'E01 conf >= 0.45'}",fill='white')
    cv2.imwrite(str(out/f"preview/clip_{clip['clip']:02d}_annotated.jpg"),images['E01_conf045_boxes'][index])
canvas.save(out/'preview/original_vs_E01.jpg',quality=94)
summary=dict(passed=True,videos=video_checks,prediction_rows=len(rows),
    confidence_threshold=0.45,all_boxes_meet_threshold=True,
    source_frame_alignment_checked_for_all_frames=True,
    original_source_visual_alignment_samples=len(indices),
    original_source_psnr_min_db=min(psnr),original_source_psnr_mean_db=float(np.mean(psnr)),
    contact_sheet='preview/original_vs_E01.jpg')
(out/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
