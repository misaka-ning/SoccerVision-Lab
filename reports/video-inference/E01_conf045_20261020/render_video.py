#!/usr/bin/env python3
"""Render paired qualitative E01 videos from selected source intervals."""
import os
os.environ.setdefault('YOLO_CONFIG_DIR', '/tmp/e01-video-yolo-config')
from pathlib import Path
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
import cv2
import torch
import ultralytics
from ultralytics import YOLO

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
SOURCE = Path('/home/misaka/temp/nvidia-recordings-20261013-181531/stereo_20261013_181531_750945_d976724b06a247158bb023f3675e05b4_first27min.avi')
WEIGHTS = ROOT / 'experiments/E01_yolo26s_single_class_finetune/E01_best.pt'
FFMPEG = Path('/home/misaka/temp/video-conversion-tools/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2')
# Chosen by inspecting source frames, before running E01 on these intervals.
CLIPS = [
    (215, 30, '近处球及距离变化'),
    (335, 30, '脚部遮挡与近距离交互'),
    (540, 25, '中距离球及机器人交互'),
    (690, 25, '相机运动与运动模糊'),
    (990, 30, '远处小球及人员交互'),
    (1085, 15, '无球及复杂人偶背景'),
    (1290, 25, '脚部遮挡及球的移动'),
]
CONF = 0.45
FPS = 15
WIDTH, HEIGHT = 1344, 376
EYE_WIDTH = WIDTH // 2
BATCH_FRAMES = 8


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def stamp(seconds):
    return f'{int(seconds)//60:02d}:{int(seconds)%60:02d}'


def encoder(name):
    log = (OUT / f'{name}.encoding.log').open('w')
    cmd = [str(FFMPEG), '-hide_banner', '-loglevel', 'warning', '-nostdin',
           '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{WIDTH}x{HEIGHT}',
           '-r', str(FPS), '-i', 'pipe:0', '-an', '-c:v', 'libx264',
           '-preset', 'fast', '-crf', '18', '-threads', '2', '-pix_fmt', 'yuv420p',
           '-movflags', '+faststart', '-n', str(OUT / f'{name}.partial.mp4')]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log), log


def draw_detection(frame, box, confidence, offset):
    x1, y1, x2, y2 = box
    x1 = int(max(0, min(EYE_WIDTH - 1, round(x1)))) + offset
    x2 = int(max(0, min(EYE_WIDTH - 1, round(x2)))) + offset
    y1 = int(max(0, min(HEIGHT - 1, round(y1))))
    y2 = int(max(0, min(HEIGHT - 1, round(y2))))
    color = (60, 240, 60)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
    label = f'football {confidence:.2f}'
    (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, .48, 1)
    tx = max(offset, min(x1, offset + EYE_WIDTH - tw - 5))
    ty = y1 - 5 if y1 > th + 36 else min(HEIGHT - baseline - 3, y2 + th + 6)
    cv2.rectangle(frame, (tx, ty - th - 3), (tx + tw + 4, ty + baseline), (12, 35, 12), -1)
    cv2.putText(frame, label, (tx + 2, ty), cv2.FONT_HERSHEY_SIMPLEX, .48, color, 1, cv2.LINE_AA)


def main():
    started = time.perf_counter()
    assert torch.cuda.is_available(), 'GPU is required for this render run'
    assert sum(length for _, length, _ in CLIPS) == 180
    for name in ('original_montage', 'E01_conf045_boxes'):
        assert not (OUT / f'{name}.mp4').exists()
        assert not (OUT / f'{name}.partial.mp4').exists()
    model = YOLO(str(WEIGHTS))
    assert model.names == {0: 'football'}
    assert model.model.model[-1].nc == 1
    cap = cv2.VideoCapture(str(SOURCE))
    assert cap.isOpened()
    assert (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))) == (WIDTH, HEIGHT)
    assert cap.get(cv2.CAP_PROP_FPS) == FPS
    source_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    raw_encoder, raw_log = encoder('original_montage')
    box_encoder, box_log = encoder('E01_conf045_boxes')
    output_index = 0
    detection_count = 0
    frames_with_detections = 0
    clips = []
    with (OUT / 'predictions.jsonl').open('w', encoding='utf-8') as pred_file:
        for clip_id, (start, duration, reason) in enumerate(CLIPS, 1):
            first = start * FPS
            count = duration * FPS
            assert cap.set(cv2.CAP_PROP_POS_FRAMES, first)
            assert int(round(cap.get(cv2.CAP_PROP_POS_FRAMES))) == first
            clips.append(dict(clip=clip_id, source_start_seconds=start, source_end_seconds=start+duration,
                source_start=stamp(start), source_end=stamp(start+duration), duration_seconds=duration,
                output_start_seconds=output_index/FPS, output_end_seconds=output_index/FPS+duration,
                source_first_frame=first, source_end_frame_exclusive=first+count, selection_reason=reason))
            for batch_start in range(0, count, BATCH_FRAMES):
                frames, eyes = [], []
                batch_count = min(BATCH_FRAMES, count-batch_start)
                for _ in range(batch_count):
                    ok, frame = cap.read()
                    assert ok and frame.shape == (HEIGHT, WIDTH, 3)
                    frames.append(frame)
                    eyes.extend((frame[:, :EYE_WIDTH].copy(), frame[:, EYE_WIDTH:].copy()))
                results = model.predict(eyes, imgsz=640, rect=False, device=0, conf=CONF,
                    iou=0.7, max_det=300, nms=True, verbose=False, save=False)
                assert len(results) == len(eyes)
                for j, frame in enumerate(frames):
                    rendered = frame.copy()
                    detections = []
                    source_index = first + batch_start + j
                    for eye_id, eye_name in enumerate(('left', 'right')):
                        result = results[j*2 + eye_id]
                        assert tuple(result.orig_shape) == (HEIGHT, EYE_WIDTH)
                        for x1,y1,x2,y2,score,cls in result.boxes.data.cpu().tolist():
                            assert int(cls) == 0 and score >= CONF
                            eye_box = [x1,y1,x2,y2]
                            draw_detection(rendered, eye_box, score, eye_id*EYE_WIDTH)
                            detections.append(dict(eye=eye_name, class_id=0, class_name='football', confidence=score,
                                xyxy_eye=eye_box, xyxy_video=[x1+eye_id*EYE_WIDTH,y1,x2+eye_id*EYE_WIDTH,y2]))
                    cv2.rectangle(rendered,(0,0),(WIDTH-1,27),(20,20,20),-1)
                    header=f'E01 | conf >= 0.45 | clip {clip_id}/7 | source {stamp(source_index/FPS)} | left / right independent inference'
                    cv2.putText(rendered,header,(9,19),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1,cv2.LINE_AA)
                    raw_encoder.stdin.write(frame.tobytes())
                    box_encoder.stdin.write(rendered.tobytes())
                    pred_file.write(json.dumps(dict(output_frame=output_index, output_time_seconds=output_index/FPS,
                        clip=clip_id, source_frame=source_index, source_time_seconds=source_index/FPS,
                        detections=detections),ensure_ascii=False)+'\n')
                    output_index += 1
                    detection_count += len(detections)
                    frames_with_detections += bool(detections)
                if output_index % 240 < BATCH_FRAMES:
                    print(f'PROGRESS {output_index}/2700 frames; elapsed {time.perf_counter()-started:.1f}s',flush=True)
            print(f'CLIP {clip_id}/7 done: source {stamp(start)}-{stamp(start+duration)}; {output_index}/2700 frames',flush=True)
    cap.release()
    assert output_index == 2700
    for process, log in ((raw_encoder, raw_log), (box_encoder, box_log)):
        process.stdin.close()
        assert process.wait() == 0, 'Video encoder failed; inspect encoding logs'
        log.close()
    for name in ('original_montage', 'E01_conf045_boxes'):
        (OUT / f'{name}.partial.mp4').rename(OUT / f'{name}.mp4')
    assert model.predictor.model.end2end is False
    manifest = dict(created_utc=datetime.now(timezone.utc).isoformat(),
        purpose='从数据集来源录像选取的定性演示，不是独立测试集评测；保留实际漏检和误检，无人工增删检测框。',
        source=dict(path=str(SOURCE), sha256=sha(SOURCE), total_frames=source_frame_count,
                    width=WIDTH,height=HEIGHT,fps=FPS,audio=False),
        model=dict(path=str(WEIGHTS),sha256=sha(WEIGHTS),names=model.names,run_id='20261019T092432Z_s42_853c4a'),
        inference=dict(conf=CONF,imgsz=640,rect=False,nms=True,nms_iou=0.7,max_det=300,
            device=torch.cuda.get_device_name(0),precision='FP32',stereo='separate inference for each 672x376 eye; boxes offset onto 1344x376 source',
            all_output_frames_inferred=True,tracking=False,temporal_smoothing=False),
        encoding=dict(codec='H.264/libx264',pixel_format='yuv420p',crf=18,fps=FPS,width=WIDTH,height=HEIGHT,
            original_montage='同一片段、原速、无框无文字，H.264重编码',annotated='逐帧模型框、类别和分数，含源录像时间'),
        duration_seconds=180,output_frame_count=output_index,clips=clips,
        detections=dict(total_boxes=detection_count,frames_with_detections=frames_with_detections),
        runtime=dict(torch=torch.__version__,ultralytics=ultralytics.__version__,opencv=cv2.__version__,elapsed_seconds=time.perf_counter()-started),
        outputs={name:dict(path=str(OUT/f'{name}.mp4'),bytes=(OUT/f'{name}.mp4').stat().st_size,
            sha256=sha(OUT/f'{name}.mp4')) for name in ('original_montage','E01_conf045_boxes')})
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'DONE {output_index} frames, {detection_count} boxes, {time.perf_counter()-started:.1f}s',flush=True)


if __name__ == '__main__':
    main()
