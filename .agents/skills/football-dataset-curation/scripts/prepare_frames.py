#!/usr/bin/env python3
"""Read-only video -> native PNG candidates, anchor dedup and review manifests.

This helper deliberately does not infer No Ball or create labels/metadata.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys


def seconds(value):
    try:
        parts = [float(p) for p in str(value).split(":")]
        if not 1 <= len(parts) <= 3 or any(not math.isfinite(p) or p < 0 for p in parts):
            raise ValueError()
        if len(parts) > 1 and any(p >= 60 for p in parts[1:]):
            raise ValueError()
        return sum(p * 60 ** k for k, p in enumerate(reversed(parts)))
    except ValueError:
        raise argparse.ArgumentTypeError("time must be nonnegative seconds, MM:SS or HH:MM:SS")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path, help="input video path (required)")
    parser.add_argument("--output", required=True, type=Path, help="new staging directory; never overwritten")
    parser.add_argument("--layout", required=True, choices=["mono", "stereo"], help="stereo = horizontal equal halves")
    parser.add_argument("--start", type=seconds, default=0., help="inclusive start time")
    parser.add_argument("--end", type=seconds, help="exclusive end time")
    parser.add_argument("--sample-fps", type=float, default=2., help="representatives/sec after dedup; 0 = every group")
    parser.add_argument("--keep-frames", type=Path, help="JSON list of source indices forced through all sampling")
    parser.add_argument("--rois", type=Path, help="JSON: source index -> eye -> list of native xywh boxes")
    parser.add_argument("--ssim", type=float, default=.90)
    parser.add_argument("--mad", type=float, default=6.)
    parser.add_argument("--tile-diff", type=float, default=22.)
    parser.add_argument("--roi-diff", type=float, default=8.)
    parser.add_argument("--coarse-every", type=float, default=1., help="seconds between coarse review thumbnails")
    args = parser.parse_args()
    if args.end is not None and args.end <= args.start:
        parser.error("--end must be later than --start")
    for key in ("sample_fps", "mad", "tile_diff", "roi_diff", "coarse_every", "ssim"):
        value = getattr(args, key)
        if not math.isfinite(value) or value < 0:
            parser.error("thresholds and sampling settings must be finite and nonnegative")
    if not 0 <= args.ssim <= 1 or args.coarse_every <= 0:
        parser.error("--ssim must be in [0,1], --coarse-every must be >0")
    return args


def run(args):
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Use a Python environment with OpenCV and NumPy; dependencies are not installed automatically") from exc
    cv2.setNumThreads(1)
    source, output = args.video.expanduser().resolve(), args.output.expanduser().resolve()
    if not source.is_file():
        raise ValueError("Video does not exist or is not a file: " + str(source))
    if output.exists():
        raise ValueError("Output must be a new directory: " + str(output))
    eyes = ["left", "right"] if args.layout == "stereo" else ["mono"]
    keep_raw = json.loads(args.keep_frames.read_text(encoding="utf-8")) if args.keep_frames else []
    if not isinstance(keep_raw, list) or any(type(i) is not int or i < 0 for i in keep_raw):
        raise ValueError("--keep-frames must contain a JSON list of nonnegative integer source indices")
    keep = set(keep_raw)
    raw_rois = json.loads(args.rois.read_text(encoding="utf-8")) if args.rois else {}
    if not isinstance(raw_rois, dict):
        raise ValueError("--rois must contain an object")
    rois = {}
    for key, eye_boxes in raw_rois.items():
        if not key.isdigit() or not isinstance(eye_boxes, dict) or any(e not in eyes for e in eye_boxes):
            raise ValueError("ROI keys must be source indices and eyes must match --layout")
        for boxes in eye_boxes.values():
            if not isinstance(boxes, list):
                raise ValueError("ROI boxes must be lists")
            for box in boxes:
                if (not isinstance(box, list) or len(box) != 4
                    or any(type(x) not in (int, float) or not math.isfinite(x) for x in box)
                    or min(box[2:]) <= 0):
                    raise ValueError("ROI boxes must be finite native xywh with positive width and height")
        rois[int(key)] = eye_boxes
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise ValueError("Cannot open video: " + str(source))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    if not math.isfinite(fps) or fps <= 0:
        cap.release()
        raise ValueError("Cannot determine video FPS; use a timestamp-aware decoder for this source")
    reported_n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    lo = int(math.ceil(args.start * fps - 1e-8))
    hi = int(math.ceil(args.end * fps - 1e-8)) if args.end is not None else None
    if any(i < lo or (hi is not None and i >= hi) for i in keep):
        cap.release()
        raise ValueError("Forced frame index is outside the requested time range")
    digest = sha256(source)
    source_id = "video_" + digest[:16]
    output.mkdir(parents=True, exist_ok=False)
    (output / "images").mkdir()
    (output / "previews").mkdir()
    groups, qualities, anchor, anchor_gray = [], {}, None, None
    frame_idx, processed, coarse, decoded_size = 0, 0, [], None
    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    codec = "".join(chr((fourcc >> (8 * k)) & 255) for k in range(4))

    def views(frame):
        if args.layout == "mono":
            return [frame]
        width = frame.shape[1]
        if width % 2:
            raise ValueError("Horizontal stereo requires an even image width")
        return [frame[:, :width // 2], frame[:, width // 2:]]

    def gray(image):
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    def thumb(image):
        return cv2.resize(image, (256, 144), interpolation=cv2.INTER_AREA).astype(np.float32)

    def compare(a, b):
        ma, mb = cv2.GaussianBlur(a, (7, 7), 1.5), cv2.GaussianBlur(b, (7, 7), 1.5)
        va = cv2.GaussianBlur(a * a, (7, 7), 1.5) - ma * ma
        vb = cv2.GaussianBlur(b * b, (7, 7), 1.5) - mb * mb
        co = cv2.GaussianBlur(a * b, (7, 7), 1.5) - ma * mb
        ssim = np.mean(((2 * ma * mb + 6.5025) * (2 * co + 58.5225)) /
                       ((ma * ma + mb * mb + 6.5025) * (va + vb + 58.5225)))
        diff = np.abs(a - b)
        return [float(ssim), float(diff.mean()), float(diff.reshape(12, 12, 16, 16).mean(axis=(1, 3)).max())]

    def roi_changed(current, old, index, anchor_index):
        for pos, eye in enumerate(eyes):
            boxes = rois.get(index, {}).get(eye, []) + rois.get(anchor_index, {}).get(eye, [])
            height, width = current[pos].shape
            for x, y, w, h in boxes:
                x0, x1 = max(0, math.floor(x) - 2), min(width, math.ceil(x + w) + 2)
                y0, y1 = max(0, math.floor(y) - 2), min(height, math.ceil(y + h) + 2)
                if x1 <= x0 or y1 <= y0:
                    raise ValueError("ROI lies outside the native eye image")
                a = current[pos][y0:y1, x0:x1].astype(np.float32)
                b = old[pos][y0:y1, x0:x1].astype(np.float32)
                diff = np.abs(a - b)
                if float(diff.mean()) > args.roi_diff or float((diff > 16).mean()) > .25:
                    return True
        return False

    def save_sheet(items, prefix, page):
        if not items:
            return
        cell_w, cell_h = 640, 236
        sheet = np.zeros((3 * cell_h, 2 * cell_w, 3), dtype=np.uint8)
        for pos, (index, frame) in enumerate(items):
            height, width = frame.shape[:2]
            scale = min(cell_w / width, (cell_h - 24) / height)
            small = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))))
            y, x = (pos // 2) * cell_h, (pos % 2) * cell_w
            sheet[y:y + small.shape[0], x:x + small.shape[1]] = small
            cv2.putText(sheet, f"frame={index} t={index / fps:.3f}s {args.layout}", (x + 5, y + cell_h - 7),
                        cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 1)
        if not cv2.imwrite(str(output / "previews" / f"{prefix}-{page:05d}.jpg"), sheet):
            raise RuntimeError("Cannot write preview")

    coarse_page = 0
    next_coarse = args.start
    try:
        with (output / "frame-metrics.jsonl").open("w", encoding="utf-8") as stream:
            while hi is None or frame_idx < hi:
                ok, frame = cap.read()
                if not ok:
                    if reported_n > 0 and frame_idx < reported_n and (hi is None or frame_idx < hi):
                        raise RuntimeError(f"Decode ended at {frame_idx}, reported frame count={reported_n}")
                    break
                index = frame_idx
                frame_idx += 1
                if index < lo:
                    continue
                current_size = list(frame.shape[:2][::-1])
                if decoded_size is not None and current_size != decoded_size:
                    raise ValueError("Video resolution changes within the selected range")
                decoded_size = current_size
                grays = [gray(view) for view in views(frame)]
                ts = [thumb(im) for im in grays]
                quality = sum(float(cv2.Laplacian(t, cv2.CV_32F).var()) for t in ts)
                comparisons = [compare(t, anchor[k]) for k, t in enumerate(ts)] if anchor is not None else []
                similar = bool(comparisons) and all(s >= args.ssim and m <= args.mad and tile <= args.tile_diff
                                                   for s, m, tile in comparisons)
                roi_change = similar and roi_changed(grays, anchor_gray, index, groups[-1]["anchor_i"])
                similar = similar and not roi_change
                if not similar:
                    groups.append({"anchor_i": index, "last_i": index, "representative_i": index,
                                   "best_quality": quality, "count": 1})
                    anchor, anchor_gray = ts, grays
                else:
                    group = groups[-1]
                    group["last_i"], group["count"] = index, group["count"] + 1
                    if quality > group["best_quality"] * 1.02:
                        group["representative_i"], group["best_quality"] = index, quality
                qualities[index] = quality
                stream.write(json.dumps({"frame_idx": index, "seconds": index / fps, "group": len(groups) - 1,
                                         "quality": quality, "similar_to_anchor": similar,
                                         "comparison": comparisons, "roi_changed": bool(roi_change)}) + "\n")
                processed += 1
                if index / fps + 1e-8 >= next_coarse:
                    coarse.append((index, frame.copy()))
                    next_coarse += args.coarse_every
                    if len(coarse) == 6:
                        save_sheet(coarse, "coarse", coarse_page)
                        coarse, coarse_page = [], coarse_page + 1
                if processed % 1000 == 0:
                    print(f"Decoded {processed} selected-range frames; {len(groups)} dedup groups", file=sys.stderr, flush=True)
        save_sheet(coarse, "coarse", coarse_page)
    finally:
        cap.release()
    if not processed:
        raise ValueError("No frames decoded in selected range")
    if any(i not in qualities for i in keep):
        raise ValueError("Forced frame index does not exist in the selected video")
    bins = {}
    for group in groups:
        index = group["representative_i"]
        key = math.floor((index - lo) * args.sample_fps / fps + 1e-8) if args.sample_fps else index
        bins.setdefault(key, []).append(index)
    reasons = {max(indices, key=lambda i: qualities[i]): ["representative"] for indices in bins.values()}
    for index in keep:
        reasons.setdefault(index, []).append("forced_hard_frame")
    selected = sorted(reasons)
    write_json(output / "dedup-groups.json", groups)
    write_json(output / "selection.json", [{"source_frame_idx": i, "reasons": reasons[i]} for i in selected])
    cap = cv2.VideoCapture(str(source))
    inventory, preview, selected_set, index, preview_page = [], [], set(selected), 0, 0
    try:
        while index <= selected[-1]:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("Second decode failed at frame " + str(index))
            if index in selected_set:
                pair_id = f"{source_id}_frame_{index:08d}"
                for eye, view in zip(eyes, views(frame)):
                    name = f"{pair_id}_{eye}.png"
                    destination = output / "images" / name
                    if not cv2.imwrite(str(destination), view):
                        raise RuntimeError("Cannot save image: " + str(destination))
                    inventory.append({"图片": name, "image_path": str(destination), "source_video": str(source),
                                      "source_frame_idx": index, "source_seconds": index / fps, "eye": eye,
                                      "pair_id": pair_id, "width": view.shape[1], "height": view.shape[0],
                                      "sha256": sha256(destination), "selection_reasons": reasons[index]})
                preview.append((index, frame.copy()))
                if len(preview) == 6:
                    save_sheet(preview, "selected", preview_page)
                    preview, preview_page = [], preview_page + 1
            index += 1
        save_sheet(preview, "selected", preview_page)
    finally:
        cap.release()
    write_json(output / "inventory.json", inventory)
    report = {"video": str(source), "sha256": digest, "source_id": source_id, "codec": codec,
              "fps": fps, "timing": "CFR indices / reported FPS; verify VFR sources separately",
              "reported_frames": reported_n, "decoded_range_frames": processed, "resolution": decoded_size,
              "start_frame_inclusive": lo, "end_frame_exclusive": lo + processed,
              "requested_end_seconds": args.end, "layout": args.layout, "dedup_groups": len(groups),
              "selected_times": len(selected), "images": len(inventory), "forced_frames": sorted(keep),
              "parameters": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
              "classification": "not performed; visual classification and label review required"}
    write_json(output / "source.json", report)
    return report


if __name__ == "__main__":
    args = arguments()
    try:
        report = run(args)
    except Exception as exc:
        print(f"ERROR: {exc}. Any partially written staging output is incomplete; use a new output directory for retry.", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(report, ensure_ascii=False, indent=2))
