#!/usr/bin/env python3
"""Read-only independent CSV, YOLO, media and split/provenance audit.

Uses the Python standard library and Pillow only; imports no project helpers.
Run with /usr/bin/python3 (the existing system Pillow installation).
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time

from PIL import Image

FLAGS = ('Small', 'Occluded', 'Blurred', 'No Ball')
SPLITS = ('train', 'val', 'test')
EPSILON = 1e-6


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_csv(raw):
    text = raw.decode('utf-8-sig')
    reader = csv.reader(io.StringIO(text, newline=''), strict=True)
    headers = next(reader)
    assert len(headers) == len(set(headers))
    records = []
    for values in reader:
        assert len(values) == len(headers)
        records.append(dict(zip(headers, values)))
    return headers, records


def parse_label(path):
    if not path.is_file() or path.is_symlink():
        return None, 'missing_or_symlink_label'
    try:
        raw = path.read_bytes()
        text = raw.decode('utf-8-sig')
    except (OSError, UnicodeError) as exc:
        return None, 'label_read_or_encoding_error: ' + str(exc)
    boxes = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5 or re.fullmatch(r'\d+', parts[0]) is None:
            return None, 'invalid_label_structure_at_line_' + str(line_number)
        try:
            cls = int(parts[0])
            x, y, w, h = map(float, parts[1:])
        except ValueError:
            return None, 'invalid_label_number_at_line_' + str(line_number)
        if cls != 0 or not all(math.isfinite(v) for v in (x, y, w, h)):
            return None, 'invalid_class_or_nonfinite_coordinate_at_line_' + str(line_number)
        if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
            return None, 'invalid_normalized_box_at_line_' + str(line_number)
        if min(x - w / 2, y - h / 2) < -EPSILON or max(x + w / 2, y + h / 2) > 1 + EPSILON:
            return None, 'box_crosses_image_boundary_at_line_' + str(line_number)
        boxes.append((cls, x, y, w, h))
    return boxes, ''


def decode_image(path):
    if not path.is_file() or path.is_symlink():
        return None, 'missing_or_symlink_image'
    try:
        with Image.open(path) as image:
            image.load()
            if image.width <= 0 or image.height <= 0:
                return None, 'nonpositive_image_dimensions'
            return (image.width, image.height, image.format), ''
    except Exception as exc:
        return None, type(exc).__name__ + ': ' + str(exc)


def counter_dict(c):
    return {str(k): v for k, v in sorted(c.items())}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    started = time.monotonic()
    root = args.dataset.absolute()
    raw = (root / 'metadata.csv').read_bytes()
    headers, rows = read_csv(raw)
    names = [r['图片'] for r in rows]
    assert len(names) == len(set(names)), 'duplicate metadata image names'
    assert all(r['split'] in SPLITS for r in rows), 'invalid split'
    assert all(r[f] in ('0', '1') for r in rows for f in FLAGS), 'invalid scene flag'
    result = {
        'independent': True,
        'canonical_dataset_written': False,
        'dataset': str(root),
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'metadata_sha256': digest(raw),
        'metadata_headers': headers,
        'metadata_utf8_bom': raw.startswith(b'\xef\xbb\xbf'),
        'criteria': {
            'both_review_flags': '0',
            'positive': 'reviewed_annotation + No Ball=0 + valid nonempty class-0 YOLO',
            'negative': 'negative_confirmed + No Ball=1 + valid empty YOLO',
            'excluded': 'reviewed_excluded is archival and never trainable or a confirmed negative',
            'image': 'regular nonsymlink image, fully decoded by Pillow.Image.load()',
            'geometry': 'finite normalized coordinates, positive sizes, all corners inside [0,1] with tolerance 1e-6',
            'four_flags': 'independent multi-label flags; their counts may overlap',
        },
        'total': len(rows),
        'unique_names': len(set(names)),
        'status': counter_dict(Counter(r['annotation_status'] for r in rows)),
        'review_flag_pairs': counter_dict(Counter(r['scene_review_required'] + r['label_review_required'] for r in rows)),
    }
    by_split = {}
    for split in SPLITS:
        by_split[split] = {
            'total': 0, 'trainable': 0, 'reviewed_excluded': 0, 'other_unusable': 0,
            'positive': 0, 'confirmed_negative': 0, 'trainable_boxes': 0,
            'all_four_flags_zero': 0, 'trainable_all_four_flags_zero': 0,
            'flags_all': dict.fromkeys(FLAGS, 0), 'flags_trainable': dict.fromkeys(FLAGS, 0),
            'status': Counter(),
        }
    all_flags = Counter()
    usable_flags = Counter()
    combinations = Counter()
    usable_combinations = Counter()
    label_errors = []
    image_errors = []
    semantic_errors = []
    reasons = Counter()
    image_shapes = Counter()
    image_formats = Counter()
    label_shapes = Counter()
    valid_boxes_all = 0
    positive_label_images = 0
    empty_label_images = 0
    excluded_with_positive_labels = 0
    excluded_with_empty_labels = 0
    excluded_with_invalid_labels = 0
    provenance_exact = defaultdict(list)
    provenance_frame = defaultdict(list)
    known_provenance_rows = 0
    expected_images = set()
    expected_labels = set()
    row_outcomes = []
    for index, row in enumerate(rows, 1):
        name = row['图片']
        split = row['split']
        assert Path(name).name == name and name not in ('.', '..')
        one = by_split[split]
        one['total'] += 1
        one['status'][row['annotation_status']] += 1
        combo = ''.join(row[f] for f in FLAGS)
        combinations[combo] += 1
        all_zero = combo == '0000'
        one['all_four_flags_zero'] += all_zero
        for flag in FLAGS:
            all_flags[flag] += int(row[flag])
            one['flags_all'][flag] += int(row[flag])
        image_path = root / 'images' / split / name
        label_path = root / 'labels' / split / (Path(name).stem + '.txt')
        expected_images.add(image_path.relative_to(root).as_posix())
        expected_labels.add(label_path.relative_to(root).as_posix())
        info, image_error = decode_image(image_path)
        boxes, label_error = parse_label(label_path)
        if image_error:
            image_errors.append({'filename': name, 'split': split, 'error': image_error})
        else:
            width, height, format_ = info
            image_shapes[f'{width}x{height}'] += 1
            image_formats[format_] += 1
        if label_error:
            label_errors.append({'filename': name, 'split': split, 'error': label_error, 'status': row['annotation_status']})
        else:
            valid_boxes_all += len(boxes)
            label_shapes[len(boxes)] += 1
            positive_label_images += bool(boxes)
            empty_label_images += not boxes
        excluded = row['annotation_status'] == 'reviewed_excluded'
        both_reviewed = row['scene_review_required'] == row['label_review_required'] == '0'
        good_positive = (row['annotation_status'] == 'reviewed_annotation' and row['No Ball'] == '0'
                         and boxes is not None and len(boxes) > 0)
        good_negative = (row['annotation_status'] == 'negative_confirmed' and row['No Ball'] == '1'
                         and boxes is not None and len(boxes) == 0)
        trainable = both_reviewed and not image_error and (good_positive or good_negative)
        row_reasons = []
        if not trainable:
            if excluded:
                row_reasons.append('reviewed_excluded')
            if not both_reviewed:
                row_reasons.append('pending_review')
            if image_error:
                row_reasons.append('invalid_image')
            if label_error:
                row_reasons.append('invalid_label')
            if not excluded and both_reviewed and not (good_positive or good_negative):
                row_reasons.append('status_NoBall_label_semantic_mismatch')
                semantic_errors.append({'filename': name, 'split': split, 'status': row['annotation_status'],
                                        'No Ball': row['No Ball'], 'box_count': None if boxes is None else len(boxes)})
            reasons.update(row_reasons)
        if excluded:
            one['reviewed_excluded'] += 1
            excluded_with_invalid_labels += boxes is None
            excluded_with_empty_labels += boxes is not None and len(boxes) == 0
            excluded_with_positive_labels += boxes is not None and len(boxes) > 0
        if trainable:
            one['trainable'] += 1
            one['positive'] += good_positive
            one['confirmed_negative'] += good_negative
            one['trainable_boxes'] += len(boxes)
            one['trainable_all_four_flags_zero'] += all_zero
            usable_combinations[combo] += 1
            for flag in FLAGS:
                usable_flags[flag] += int(row[flag])
                one['flags_trainable'][flag] += int(row[flag])
        elif not excluded:
            one['other_unusable'] += 1
        if row['source_video'] and row['source_frame_idx'] and row['eye']:
            known_provenance_rows += 1
            frame_idx = row['source_frame_idx']
            if frame_idx.isdigit():
                frame_idx = str(int(frame_idx))
            provenance_exact[(row['source_video'], frame_idx, row['eye'])].append((split, row['eye']))
            provenance_frame[(row['source_video'], frame_idx)].append((split, row['eye']))
        row_outcomes.append({'filename': name, 'split': split, 'status': row['annotation_status'], 'trainable': trainable,
                             'valid_boxes': None if boxes is None else len(boxes), 'unusable_reasons': row_reasons})
        if index % 1000 == 0:
            print(f'independent decoded {index}/{len(rows)}', flush=True)
    for one in by_split.values():
        one['status'] = counter_dict(one['status'])
    result['split'] = by_split
    result['flags_all'] = {flag: all_flags[flag] for flag in FLAGS}
    result['flags_trainable'] = {flag: usable_flags[flag] for flag in FLAGS}
    result['flag_combinations_all'] = counter_dict(combinations)
    result['flag_combinations_trainable'] = counter_dict(usable_combinations)
    result['all_four_flags_zero'] = combinations['0000']
    result['trainable_all_four_flags_zero'] = usable_combinations['0000']
    result['trainable'] = sum(s['trainable'] for s in by_split.values())
    result['reviewed_excluded'] = sum(s['reviewed_excluded'] for s in by_split.values())
    result['other_unusable'] = sum(s['other_unusable'] for s in by_split.values())
    result['positive'] = sum(s['positive'] for s in by_split.values())
    result['confirmed_negative'] = sum(s['confirmed_negative'] for s in by_split.values())
    result['trainable_boxes'] = sum(s['trainable_boxes'] for s in by_split.values())
    result['pending_any_review_flag'] = sum(r['scene_review_required'] != '0' or r['label_review_required'] != '0' for r in rows)
    result['both_reviewed'] = sum(r['scene_review_required'] == r['label_review_required'] == '0' for r in rows)
    result['image_validation'] = {'decoded': len(rows) - len(image_errors), 'errors': image_errors,
                                  'dimensions': counter_dict(image_shapes), 'formats': counter_dict(image_formats)}
    result['label_validation'] = {'valid': len(rows) - len(label_errors), 'invalid': len(label_errors), 'errors': label_errors,
                                  'valid_box_count_all': valid_boxes_all, 'positive_label_images': positive_label_images,
                                  'empty_label_images': empty_label_images, 'boxes_per_image': counter_dict(label_shapes),
                                  'excluded_valid_nonempty': excluded_with_positive_labels,
                                  'excluded_valid_empty': excluded_with_empty_labels, 'excluded_invalid': excluded_with_invalid_labels}
    result['unusable_reasons_multilabel'] = counter_dict(reasons)
    result['semantic_errors_outside_excluded'] = semantic_errors
    actual_images = {p.relative_to(root).as_posix() for p in (root / 'images').rglob('*') if p.is_file() and p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp', '.webp')}
    actual_labels = {p.relative_to(root).as_posix() for p in (root / 'labels').rglob('*.txt') if p.is_file()}
    result['physical_inventory'] = {'image_files': len(actual_images), 'label_files': len(actual_labels),
        'missing_metadata_images': sorted(expected_images - actual_images), 'extra_images_without_metadata': sorted(actual_images - expected_images),
        'missing_metadata_labels': sorted(expected_labels - actual_labels), 'extra_labels_without_metadata': sorted(actual_labels - expected_labels)}
    exact_overlap = [v for v in provenance_exact.values() if len({s for s, eye in v}) > 1]
    frame_overlap = [v for v in provenance_frame.values() if len({s for s, eye in v}) > 1]
    stereo_overlap = [v for v in frame_overlap if any(s1 != s2 and e1 != e2 for s1, e1 in v for s2, e2 in v)]
    result['provenance_overlap'] = {'basis': 'explicit source_video + source_frame_idx + eye; no filename inference',
        'rows_complete_provenance': known_provenance_rows, 'rows_incomplete_provenance': len(rows) - known_provenance_rows,
        'exact_eye_frame_groups_across_splits': len(exact_overlap), 'exact_eye_frame_rows_across_splits': sum(map(len, exact_overlap)),
        'source_frame_groups_across_splits': len(frame_overlap), 'source_frame_rows_across_splits': sum(map(len, frame_overlap)),
        'left_right_same_frame_groups_across_splits': len(stereo_overlap),
        'left_right_same_frame_rows_across_splits': sum(map(len, stereo_overlap)),
        'limitation': 'Incomplete explicit provenance cannot be used to establish or exclude overlap.'}
    result['metadata_unchanged_during_audit'] = (root / 'metadata.csv').read_bytes() == raw
    result['elapsed_seconds'] = round(time.monotonic() - started, 3)
    result['checks'] = {
        'expected8398': len(rows) == 8398,
        'images_all_decode': not image_errors,
        'all_images_and_labels_match_metadata': actual_images == expected_images and actual_labels == expected_labels,
        'all_review_flags_zero': result['pending_any_review_flag'] == 0,
        'trainable_plus_excluded_plus_other_equals_total': result['trainable'] + result['reviewed_excluded'] + result['other_unusable'] == len(rows),
        'nonexcluded_semantics_valid': not semantic_errors,
        'metadata_unchanged_during_audit': result['metadata_unchanged_during_audit'],
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    args.output.with_name('independent-row-outcomes.json').write_text(json.dumps(row_outcomes, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('total', 'status', 'split', 'flags_all', 'flags_trainable', 'trainable', 'reviewed_excluded', 'other_unusable', 'positive', 'confirmed_negative', 'trainable_boxes', 'pending_any_review_flag', 'provenance_overlap', 'checks', 'elapsed_seconds')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
