#!/usr/bin/env python3
"""Read-only dataset census after the final user-confirmed review."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sys

from PIL import Image

OUT = Path(__file__).resolve().parent
DATA = Path('/home/misaka/workspace/datasets')
sys.path.insert(0, str(OUT.parents[1] / 'confidence-review-20261014'))
import audit_io as h

FLAGS = ('Small', 'Occluded', 'Blurred', 'No Ball')


def save(name, value):
    path = OUT / name
    assert not path.exists(), path
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def aggregate(records):
    usable = [r for r in records if r['usable']]
    return dict(
        total=len(records), usable=len(usable), unusable=len(records)-len(usable),
        reviewed_excluded=sum(r['status'] == 'reviewed_excluded' for r in records),
        pending=sum(not r['double_reviewed'] for r in records),
        reviewed_positive=sum(r['status'] == 'reviewed_annotation' for r in records),
        confirmed_negative=sum(r['status'] == 'negative_confirmed' for r in records),
        usable_positive=sum(r['status'] == 'reviewed_annotation' for r in usable),
        usable_negative=sum(r['status'] == 'negative_confirmed' for r in usable),
        statuses=dict(Counter(r['status'] for r in records)),
        flags_all={k: sum(r['flags'][k] for r in records) for k in FLAGS},
        flags_usable={k: sum(r['flags'][k] for r in usable) for k in FLAGS},
        flags_excluded={k: sum(r['flags'][k] for r in records
                               if r['status'] == 'reviewed_excluded') for k in FLAGS},
        all_zero=sum(not any(r['flags'].values()) for r in records),
        all_zero_usable=sum(not any(r['flags'].values()) for r in usable),
        valid_label_files=sum(r['label_valid'] for r in records),
        nonempty_labels=sum(r['label_valid'] and r['box_count'] > 0 for r in records),
        empty_labels=sum(r['label_valid'] and r['box_count'] == 0 for r in records),
        boxes_all_valid_labels=sum(r['box_count'] or 0 for r in records if r['label_valid']),
        boxes_usable=sum(r['box_count'] for r in usable),
        multi_ball_images_all=sum(r['label_valid'] and r['box_count'] > 1 for r in records),
        multi_ball_images_usable=sum(r['box_count'] > 1 for r in usable),
        box_count_histogram=dict(Counter(str(r['box_count']) for r in records)),
        resolutions=dict(Counter(r['resolution'] for r in records if r['image_valid'])),
        formats=dict(Counter(r['format'] for r in records if r['image_valid'])),
        excluded_original_status=dict(Counter(r['excluded_original_status'] for r in records
                                             if r['status'] == 'reviewed_excluded')),
    )


def main():
    raw = (DATA / 'metadata.csv').read_bytes()
    rows = h.csv_parts(raw)['rows']
    names = [r['图片'] for r in rows]
    assert len(names) == len(set(names))
    records, issues = [], []
    expected_images, expected_labels = set(), set()
    hashes = defaultdict(list)
    source_frames = defaultdict(list)
    source_videos = defaultdict(list)
    for row in rows:
        name, split = row['图片'], row['split']
        assert all(row[k] in ('0', '1') for k in (*FLAGS, 'label_review_required', 'scene_review_required'))
        ip = DATA / 'images' / split / name
        lp = DATA / 'labels' / split / (Path(name).stem + '.txt')
        expected_images.add(str(ip.relative_to(DATA)))
        expected_labels.add(str(lp.relative_to(DATA)))
        image_error = label_error = ''
        resolution = fmt = ''
        image_sha = label_sha = ''
        count = None
        try:
            b = h.regular_under(ip, DATA).read_bytes()
            image_sha = hashlib.sha256(b).hexdigest()
            with Image.open(io.BytesIO(b)) as im:
                resolution = f'{im.width}x{im.height}'
                fmt = im.format
                im.verify()
            hashes[image_sha].append(dict(filename=name, split=split))
        except Exception as exc:
            image_error = str(exc)
        try:
            b = h.regular_under(lp, DATA).read_bytes()
            label_sha = hashlib.sha256(b).hexdigest()
            count = len(h.label_boxes(b.removeprefix(b'\xef\xbb\xbf'), boundary_tolerance=1e-6))
        except Exception as exc:
            label_error = str(exc)
        double_reviewed = row['label_review_required'] == row['scene_review_required'] == '0'
        status = row['annotation_status']
        status_ok = ((status == 'reviewed_annotation' and count is not None and count > 0 and row['No Ball'] == '0')
                     or (status == 'negative_confirmed' and count == 0 and row['No Ball'] == '1'))
        usable = double_reviewed and status_ok and not image_error and not label_error
        reasons = []
        if status == 'reviewed_excluded': reasons.append('reviewed_excluded')
        if not double_reviewed: reasons.append('review_pending')
        if image_error: reasons.append('image_error')
        if label_error: reasons.append('label_error')
        if not status_ok and status != 'reviewed_excluded': reasons.append('status_or_NoBall_mismatch')
        old_status = re.findall(r'原处置=([^；]+)', row['label_review_note'])
        item = dict(filename=name, split=split, status=status, flags={k:int(row[k]) for k in FLAGS},
                    double_reviewed=double_reviewed, usable=usable, reasons=reasons,
                    image_valid=not image_error, label_valid=not label_error, box_count=count,
                    image_error=image_error, label_error=label_error, image_sha256=image_sha,
                    label_sha256=label_sha, resolution=resolution, format=fmt,
                    excluded_original_status=old_status[-1] if old_status else '未记录',
                    source_video=row.get('source_video',''), source_frame_idx=row.get('source_frame_idx',''),
                    eye=row.get('eye',''))
        records.append(item)
        if image_error or label_error or (not status_ok and status != 'reviewed_excluded'):
            issues.append(item)
        if item['source_video']:
            source_videos[item['source_video']].append(item)
            if item['source_frame_idx']:
                source_frames[(item['source_video'],item['source_frame_idx'])].append(item)

    actual_images = {str(p.relative_to(DATA)) for p in (DATA/'images').rglob('*')
                     if p.is_file() and p.suffix.lower() in ('.jpg','.jpeg','.png','.webp','.bmp','.tif','.tiff')}
    actual_labels = {str(p.relative_to(DATA)) for p in (DATA/'labels').rglob('*.txt') if p.is_file()}
    missing_images, extra_images = sorted(expected_images-actual_images), sorted(actual_images-expected_images)
    missing_labels, extra_labels = sorted(expected_labels-actual_labels), sorted(actual_labels-expected_labels)
    exact_duplicates = [v for v in hashes.values() if len(v)>1]
    cross_split_frames = [{'source_video':k[0], 'source_frame_idx':k[1],
                           'images':[{'filename':x['filename'],'split':x['split'],'eye':x['eye']} for x in v]}
                          for k,v in source_frames.items() if len({r['split'] for r in v})>1]
    assert (DATA/'metadata.csv').read_bytes() == raw, 'Metadata changed during census; rerun from fresh data'
    result = dict(dataset=str(DATA),created_at_utc=datetime.now(timezone.utc).isoformat(),
                  metadata_sha256=hashlib.sha256(raw).hexdigest(),
                  definition='usable requires both reviews complete, reviewed_annotation with valid nonempty class0 label and No Ball=0, or negative_confirmed with valid empty label and No Ball=1, plus a valid image. reviewed_excluded is always kept out.',
                  overall=aggregate(records),
                  splits={s:aggregate([r for r in records if r['split']==s]) for s in ('train','val','test')},
                  quality=dict(actual_image_files=len(actual_images),actual_label_files=len(actual_labels),
                               missing_images=missing_images,extra_images=extra_images,
                               missing_labels=missing_labels,extra_labels=extra_labels,
                               invalid_images=sum(not r['image_valid'] for r in records),
                               invalid_labels=sum(not r['label_valid'] for r in records),
                               nonexcluded_NoBall_or_status_mismatches=sum('status_or_NoBall_mismatch' in r['reasons'] for r in records),
                               exact_duplicate_groups=len(exact_duplicates),
                               exact_duplicate_images=sum(map(len,exact_duplicates)),
                               exact_duplicate_cross_split_groups=sum(len({r['split'] for r in g})>1 for g in exact_duplicates),
                               source_frame_cross_split_groups=len(cross_split_frames),
                               source_video_count=len(source_videos)),
                  scene_combinations_all=dict(Counter(''.join(str(r['flags'][k]) for k in FLAGS) for r in records)),
                  scene_combinations_usable=dict(Counter(''.join(str(r['flags'][k]) for k in FLAGS) for r in records if r['usable'])),
                  source_videos=[dict(source_video=k, **aggregate(v)) for k,v in source_videos.items()])
    save('statistics.json',result)
    save('image-inventory.json',records)
    save('unusable-images.json',[r for r in records if not r['usable']])
    save('quality-details.json',dict(issues=issues,exact_duplicates=exact_duplicates,cross_split_frames=cross_split_frames))
    (OUT/'source-metadata.csv').write_bytes(raw)
    print(json.dumps(dict(overall=result['overall'],splits={s:{k:v[k] for k in ('total','usable','reviewed_excluded','usable_positive','usable_negative')} for s,v in result['splits'].items()},quality=result['quality']),ensure_ascii=False,indent=2))


if __name__ == '__main__': main()
