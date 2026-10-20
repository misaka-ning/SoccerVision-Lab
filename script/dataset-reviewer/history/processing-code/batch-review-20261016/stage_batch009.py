#!/usr/bin/env python3
"""Save batch 9 proposals and pending previews without changing the live dataset.

The user is reviewing batch 8 in Qt. Its metadata hash must remain valid for
their next save, so applying batch 9 is deliberately deferred until that ends.
The preview is an audit artifact; never copy its full CSV onto the live dataset.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import apply_precheck as precheck

h = precheck.h
HERE = Path(__file__).resolve().parent
BATCH = HERE.parent / 'review-reset-20261015' / 'batch-009'
DATASET = HERE.parents[1] / 'datasets'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-date', required=True)
    args = parser.parse_args()
    datetime.strptime(args.review_date, '%Y-%m-%d')
    inputs = {name: (BATCH / name).read_bytes() for name in (
        'inventory.json', 'proposals.json', 'summary.json',
        'replacement-second-review.json')}
    baseline, proposals, collected, second = (
        json.loads(inputs[name]) for name in inputs)
    assert len(baseline) == len(proposals) == collected['images'] == 398
    assert [q['filename'] for q in proposals] == [b['filename'] for b in baseline]
    assert all(q['label_review_required'] == q['scene_review_required'] == '1'
               and q['user_approved'] is False for q in proposals)
    replacements = {q['filename']: q for q in proposals if q['action'] == 'replace'}
    assert len(second) == len(replacements)
    assert {q['filename'] for q in second} == set(replacements)
    for review in second:
        q = replacements[review['filename']]
        assert review['reviewed_boxes_xyxy'] == q['boxes_xyxy']
        assert review['approved'] is False
        assert review['second_pass_accept_candidate'] is True
        assert review['reviewer'] == 'root_independent_native_visual_second_pass'
        assert review['assessment'] and review['evidence']
        assert all(Path(p).is_file() for p in review['evidence'])
    for name, sha in collected['input_sha256'].items():
        assert h.digest(Path(name).read_bytes()) == sha, name
    mp, raw, parsed, accepted, skipped = precheck.plan(
        DATASET, baseline, proposals, batch=9, review_date=args.review_date)
    assert len(accepted) == 398 and not skipped
    preview = h.csv_update(parsed, {x['filename']: x['pending_meta'] for x in accepted})
    preview_rows = {r['图片']: r for r in h.csv_parts(preview)['rows']}
    for item in accepted:
        row = preview_rows[item['filename']]
        boxes = h.label_boxes(item['replacement'], boundary_tolerance=1e-6)
        assert row['No Ball'] == ('0' if boxes else '1')
        assert row['label_review_required'] == row['scene_review_required'] == '1'

    out = BATCH / 'staged'
    out.mkdir(exist_ok=False)
    for name, data in inputs.items():
        h.save_exclusive(out / name, data)
    h.save_exclusive(out / 'before/metadata.csv', raw)
    h.save_exclusive(out / 'preview/metadata.csv', preview)
    for item in accepted:
        rel = Path(item['split']) / item['path'].name
        h.save_exclusive(out / 'before/labels' / rel, item['original'])
        if item['replacement'] != item['original']:
            h.save_exclusive(out / 'proposed/labels' / rel, item['replacement'])
    # The live CSV can legitimately change while the user saves batch 8.
    # Validate the 398 target rows and media again, without blocking their GUI.
    latest = {r['图片']: r for r in h.csv_parts(mp.read_bytes())['rows']}
    for b in baseline:
        assert latest[b['filename']] == b['meta']
        assert h.digest(Path(b['image_path']).read_bytes()) == b['image_sha256']
        assert h.digest(Path(b['label_path']).read_bytes()) == b['label_sha256']
    for name, data in inputs.items():
        assert (BATCH / name).read_bytes() == data
    result = precheck.summary(accepted, skipped)
    result.update(
        batch=9, status='ready_to_apply_after_batch_8_review',
        canonical_dataset_written=False, canonical_metadata_written=False,
        canonical_labels_written=0, window_opened=False,
        user_approved=0, all_require_user_review=True,
        scene_rows_changed=collected['scene_rows_changed'],
        flags=collected['flags'], priority=collected['priority'],
        full_pages=collected['full_pages'], roi_pages=collected['roi_pages'],
        input_sha256={name: h.digest(data) for name, data in inputs.items()},
        metadata_observed_sha256=h.digest(raw),
        preview_metadata_sha256=h.digest(preview),
        review_date=args.review_date,
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        staged_directory=str(out),
        next_step='After user finishes batch 8, run apply_precheck.py --batch 9 '
                  '--review-date with the current date --apply; its Qt locks '
                  'and fresh row/media checks preserve subsequent user edits. '
                  'Never install the stale preview CSV directly.')
    precheck.save(out / 'result.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
