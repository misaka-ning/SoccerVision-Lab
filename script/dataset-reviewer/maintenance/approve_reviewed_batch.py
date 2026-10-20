#!/usr/bin/env python3
"""Record an explicitly user-completed batch without editing annotations/scenes.

snapshot is read-only; approve is dry-run unless --apply is supplied. Approval
holds the reviewer's native Qt label/metadata locks and rejects any selected
metadata field, image or label changed since the snapshot. Excluded samples
remain archival references rather than becoming training negatives.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from review_paths import LOCK_RUNNER

SHARED = Path(__file__).resolve().parent
sys.path.insert(0, str(SHARED))
import audit_io as h

UNCERTAIN = {'uncertain', 'severe_blur', 'severe_occlusion', 'uncertain_bbox', 'temporal_only', 'fully_occluded'}
MARKER = '2026-10-16 用户明确确认本批 label 和场景均已人工审核完成。'


def save_json(path, value):
    h.save_exclusive(path, (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode())


def parsed_label(data):
    try:
        return h.label_boxes(data.removeprefix(b'\xef\xbb\xbf'), boundary_tolerance=1e-6), ''
    except (ValueError, UnicodeError) as exc:
        return [], str(exc)


def snapshot(root, image_list, output, expected_count):
    metadata = h.regular_under(root/'metadata.csv', root)
    raw = metadata.read_bytes(); parsed = h.csv_parts(raw)
    names = [n.strip() for n in image_list.read_text(encoding='utf-8-sig').splitlines() if n.strip()]
    if len(names) != expected_count or len(set(names)) != len(names):
        raise ValueError('Image list count or uniqueness differs from the requested batch')
    rows = {r['图片']: r for r in parsed['rows']}; records = []
    for name in names:
        h.name_of({'filename': name}); r = rows[name]
        image = h.regular_under(root/'images'/r['split']/name, root)
        label = h.regular_under(root/'labels'/r['split']/(Path(name).stem+'.txt'), root)
        ib = image.read_bytes(); lb = label.read_bytes()
        _, label_error = parsed_label(lb)
        records.append({'filename': name, 'meta': r, 'image_sha256': h.digest(ib), 'label_sha256': h.digest(lb), 'label_validation_error': label_error})
    if metadata.read_bytes() != raw:
        raise ValueError('Metadata changed while collecting the snapshot; retry with a fresh output')
    value = {'dataset': str(root), 'image_list': str(image_list), 'image_list_sha256': h.digest(image_list.read_bytes()),
             'metadata_sha256': h.digest(raw), 'headers': parsed['headers'], 'records': records,
             'created_at_utc': datetime.now(timezone.utc).isoformat()}
    save_json(output, value)
    return {'snapshot': str(output), 'count': len(records)}


def plan(root, baseline, marker=MARKER):
    if str(root) != baseline['dataset']:
        raise ValueError('Snapshot belongs to a different dataset')
    raw = h.regular_under(root/'metadata.csv', root).read_bytes(); parsed = h.csv_parts(raw)
    if parsed['headers'] != baseline['headers']:
        raise ValueError('Metadata schema changed after snapshot')
    current = {r['图片']: r for r in parsed['rows']}; updates = {}; details = []
    for b in baseline['records']:
        name = h.name_of(b); r = current[name]
        if r != b['meta']:
            raise ValueError('Selected metadata changed after snapshot: '+name)
        image = h.regular_under(root/'images'/r['split']/name, root)
        label = h.regular_under(root/'labels'/r['split']/(Path(name).stem+'.txt'), root)
        if h.digest(image.read_bytes()) != b['image_sha256']:
            raise ValueError('Selected image changed after snapshot: '+name)
        lb = label.read_bytes()
        if h.digest(lb) != b['label_sha256']:
            raise ValueError('Selected label changed after snapshot: '+name)
        boxes, label_error = parsed_label(lb)
        excluded = label_error or r['annotation_status'] in UNCERTAIN or r['annotation_status'] == 'reviewed_excluded' or (not boxes and r['No Ball'] != '1') or (boxes and r['No Ball'] != '0')
        status = 'reviewed_excluded' if excluded else 'reviewed_annotation' if boxes else 'negative_confirmed'
        new = dict(r, annotation_status=status, label_review_required='0', scene_review_required='0')
        note = marker
        if excluded:
            note += ' 原处置='+r['annotation_status']+'；保留原框和四类分类，已审核并暂不进入训练；不可将空框推断为无球。'
            if label_error: note += ' 原 label 格式或几何校验：'+label_error
        new['label_review_note'] = (r.get('label_review_note', '')+' '+note).strip()
        updates[name] = new
        details.append({'filename': name, 'previous_status': r['annotation_status'], 'annotation_status': status,
                        'No Ball': r['No Ball'], 'box_count': len(boxes) if not label_error else None, 'label_validation_error': label_error,
                        'image_sha256': b['image_sha256'], 'label_sha256': b['label_sha256']})
    return raw, parsed, updates, details


def apply_locked(root, baseline, audit, expect_excluded=None, marker=MARKER):
    raw, parsed, updates, details = plan(root, baseline, marker)
    counts = dict(Counter(r['annotation_status'] for r in details))
    if expect_excluded is not None and counts.get('reviewed_excluded', 0) != expect_excluded:
        raise ValueError('Excluded count differs from inspected/authorized plan')
    audit.mkdir(parents=True, exist_ok=False)
    h.save_exclusive(audit/'before/metadata.csv', raw)
    save_json(audit/'before/inventory.json', baseline)
    save_json(audit/'approved-records.json', details)
    # Recheck every selected field and both file hashes immediately before the
    # atomic metadata-only write. Unselected rows retain their latest raw bytes.
    again, _, again_updates, _ = plan(root, baseline, marker)
    if again != raw or again_updates != updates:
        raise ValueError('Data changed during approval; zero metadata writes')
    replacement = h.csv_update(parsed, updates)
    h.atomic_replace(root/'metadata.csv', replacement, raw)
    result = {'count': len(updates), 'counts': counts, 'label_review_required': 0, 'scene_review_required': 0,
              'images_written': 0, 'labels_written': 0, 'scene_values_written': 0,
              'metadata_before_sha256': h.digest(raw), 'metadata_after_sha256': h.digest(replacement),
              'audit': str(audit), 'created_at_utc': datetime.now(timezone.utc).isoformat()}
    save_json(audit/'result.json', result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['snapshot', 'approve'])
    p.add_argument('--dataset', type=Path, help='显式覆盖数据集；默认script/config.yaml')
    p.add_argument('--image-list', type=Path)
    p.add_argument('--snapshot', type=Path, required=True)
    p.add_argument('--expect-count', type=int, default=1000)
    p.add_argument('--expect-excluded', type=int)
    p.add_argument('--audit-dir', type=Path)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--review-date', type=date.fromisoformat,
                   help='Human confirmation date (YYYY-MM-DD), recorded in review notes')
    p.add_argument('--locked', action='store_true', help=argparse.SUPPRESS)
    a = p.parse_args()
    from review_paths import current_dataset
    root = (a.dataset or current_dataset()).absolute()
    marker = (a.review_date.isoformat() + ' 用户明确确认本批 label 和场景均已人工审核完成。') if a.review_date else MARKER
    if a.mode == 'snapshot':
        if not a.image_list: p.error('snapshot requires --image-list')
        result = snapshot(root, a.image_list.absolute(), a.snapshot.absolute(), a.expect_count)
    else:
        b = h.read_json(a.snapshot)
        if len(b['records']) != a.expect_count: raise ValueError('Snapshot has an unexpected count')
        if not a.apply:
            _, _, updates, details = plan(root, b, marker)
            result = {'dry_run': True, 'count': len(updates), 'counts': dict(Counter(x['annotation_status'] for x in details))}
        elif not a.audit_dir:
            p.error('approval requires --audit-dir')
        elif a.locked:
            result = apply_locked(root, b, a.audit_dir.absolute(), a.expect_excluded, marker)
        else:
            locks = sorted(str(root/'labels'/r['meta']['split']/(Path(r['filename']).stem+'.txt'))+'.review.lock' for r in b['records'])
            locks.append(str(root/'metadata.csv')+'.review.lock')
            lock_path = a.snapshot.with_name(a.snapshot.stem+'.locks-'+uuid4().hex[:8]+'.json')
            save_json(lock_path, locks)
            command = [str(LOCK_RUNNER), '--lock-list', str(lock_path), '--', sys.executable,
                       str(Path(__file__).resolve()), *sys.argv[1:], '--locked']
            raise SystemExit(subprocess.run(command).returncode)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
