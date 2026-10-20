#!/usr/bin/env python3
"""Validate the complete visual decisions before publication; never edits dataset."""
import json
from pathlib import Path
from collections import Counter

HERE = Path(__file__).resolve().parent
FLAGS = ('Small', 'Occluded', 'Blurred', 'No Ball')
PENDING = {'auto_label_needs_review', 'needs_visibility_review', 'needs_manual_bbox_annotation'}

def main():
    baseline = json.loads((HERE / 'pending-inventory.json').read_text())
    baseline_by_name = {b['filename']: b for b in baseline}
    combined, groups, seen = [], [], set()
    for number in (1, 2, 3):
        folder = HERE / f'group-{number}'
        inventory = json.loads((folder / 'inventory.json').read_text())
        decisions = json.loads((folder / 'decisions.json').read_text())
        summary = json.loads((folder / 'summary.json').read_text())
        assert isinstance(decisions, list), f'group-{number}: decisions must be a list'
        expected = {b['filename'] for b in inventory}
        assert len(decisions) == len(expected)
        assert {d['filename'] for d in decisions} == expected
        group_counter = Counter()
        for source in decisions:
            d = dict(source)
            name = d['filename']
            assert name not in seen, f'Duplicate {name}'
            seen.add(name)
            b = baseline_by_name[name]
            assert d['index'] == b['index'], name
            assert d.get('scene_seen') is True, f'{name}: scene not opened'
            assert not b['boxes'] or d.get('roi_seen') is True, f'{name}: ROI not opened'
            assert d['expected_image_sha256'] == b['image_sha256'], name
            assert d['expected_label_sha256'] == b['label_sha256'], name
            assert d['label_decision'] in {'approve_positive', 'approve_negative', 'retain', 'already_confirmed'}
            assert d['scene_decision'] in {'approve', 'retain', 'already_confirmed'}
            assert isinstance(d.get('reason'), str) and d['reason'].strip(), name
            assert set(d['flags']) == set(FLAGS), name
            d['flags'] = {k: str(d['flags'][k]) for k in FLAGS}
            assert all(v in {'0', '1'} for v in d['flags'].values()), name
            old = b['meta']
            # Scene-only work never rebrands existing user/provided label decisions.
            label_pending = old['label_review_required'] == '1' or old['annotation_status'] in PENDING
            if not label_pending:
                d['label_decision'] = 'already_confirmed'
            else:
                assert d['label_decision'] != 'already_confirmed', name
            if d['scene_decision'] == 'already_confirmed':
                assert old['scene_review_required'] == '0', name
            paths = []
            for item in d.get('native_evidence', []):
                p = Path(item)
                if not p.is_absolute():
                    p = folder / p
                p = p.resolve()
                assert p.is_file(), f'{name}: missing native evidence {p}'
                paths.append(str(p))
            d['native_evidence'] = paths
            if d['label_decision'] == 'approve_negative':
                assert not b['boxes'] and b['label_text'] == '', name
                assert paths, f'{name}: negative lacks native visual evidence'
            if d['label_decision'] == 'approve_positive':
                assert b['boxes'], name
            d['review_group'] = number
            group_counter[(d['label_decision'], d['scene_decision'])] += 1
            combined.append(d)
        groups.append({'group': number, 'images': len(inventory), 'existing_boxes': sum(len(b['boxes']) for b in inventory),
                       'component_decisions': {str(k): v for k, v in group_counter.items()}, 'visual_summary': summary})
    assert seen == set(baseline_by_name), 'Incomplete pending coverage'
    combined.sort(key=lambda d: d['index'])
    (HERE / 'combined-decisions.json').write_text(json.dumps(combined, ensure_ascii=False, indent=2) + '\n')
    output = {'pending_images_reviewed': len(combined), 'existing_boxes_reviewed': sum(len(b['boxes']) for b in baseline),
              'label_decisions': dict(Counter(d['label_decision'] for d in combined)),
              'scene_decisions': dict(Counter(d['scene_decision'] for d in combined)), 'groups': groups}
    (HERE / 'visual-coverage.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in output.items() if k != 'groups'}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
