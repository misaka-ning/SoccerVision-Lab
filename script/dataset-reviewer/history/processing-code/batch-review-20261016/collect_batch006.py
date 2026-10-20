#!/usr/bin/env python3
"""Validate four complete independent visual groups, then collect pending proposals.

Reads the canonical dataset to verify the inventory hashes; never writes it.
Every group must supply its own proposals.json and summary.json. The opened-page
lists are the reviewers' recorded visual evidence, not an inferred reading log.
"""
from collections import Counter
import json
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'review-reset-20261015'
BATCH = SOURCE / 'batch-006'
DATASET = HERE.parents[1] / 'datasets'
SHARED = HERE.parent / 'confidence-review-20261014'
sys.path.insert(0, str(SHARED))
import audit_io as h

FLAGS = ('Small', 'Occluded', 'Blurred', 'No Ball')
ACTIONS = {'keep', 'replace', 'needs_manual_bbox_annotation', 'needs_visibility_review'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def evidence_path(value, directory, source_image=None):
    require(isinstance(value, str) and Path(value).is_absolute(),
            f'Evidence must be an absolute path: {value!r}')
    # A reviewer may also inspect this exact native source image directly.
    # Other dataset files remain outside the permitted evidence scope.
    raw_path = Path(value)
    root = DATASET if source_image is not None and raw_path == source_image else directory
    path = h.regular_under(raw_path, root)
    require(str(path) == str(path.resolve()), f'Non-canonical evidence path: {value}')
    return str(path)


def opened_pages(summary, key, expected, directory):
    values = summary.get(key)
    require(isinstance(values, list), f'{directory.name}: missing actual path list {key}')
    paths = [evidence_path(value, directory) for value in values]
    require(len(paths) == len(set(paths)) and set(paths) == set(expected),
            f'{directory.name}: incomplete/duplicate actual opened pages in {key}')
    return paths


def replacement_label(proposal, baseline):
    boxes = proposal.get('boxes_xyxy')
    require(isinstance(boxes, list), f'{baseline["filename"]}: replace needs boxes_xyxy')
    width, height = baseline['width'], baseline['height']
    require(type(width) is int and type(height) is int and width > 0 and height > 0,
            f'{baseline["filename"]}: invalid image dimensions')
    lines = []
    for box in boxes:
        require(isinstance(box, list) and len(box) == 4,
                f'{baseline["filename"]}: invalid replacement box')
        require(all(type(value) in (int, float) and math.isfinite(value) for value in box),
                f'{baseline["filename"]}: non-finite/non-numeric replacement coordinates')
        x1, y1, x2, y2 = box
        require(0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height,
                f'{baseline["filename"]}: replacement box outside image or degenerate: {box}')
        lines.append(f'0 {(x1+x2)/(2*width):.10f} {(y1+y2)/(2*height):.10f} '
                     f'{(x2-x1)/width:.10f} {(y2-y1)/height:.10f}')
    data = ('\n'.join(lines) + ('\n' if lines else '')).encode('utf-8')
    h.label_boxes(data, boundary_tolerance=1e-6)
    return data


def main():
    # Refuse to start collection while even one independent group is unfinished.
    required = [BATCH / 'inventory.json', HERE / 'review-policy.json']
    required += [BATCH / f'group-{group}' / name for group in range(1, 5)
                 for name in ('inventory.json', 'manifest.json', 'proposals.json', 'summary.json')]
    missing = [str(path) for path in required if not path.is_file()]
    require(not missing, 'Four complete groups are required; missing: ' + ', '.join(missing))
    input_bytes = {path: path.read_bytes() for path in required}
    read = lambda path: json.loads(input_bytes[path].decode('utf-8'))
    policy = read(HERE / 'review-policy.json')
    require(policy.get('effective_from_batch') == 5 and
            all(isinstance(policy.get(key), str) and policy[key].strip()
                for key in (*FLAGS, 'review', 'authority')),
            'Missing or unexpected active review policy (effective from batch 5)')
    base = read(BATCH / 'inventory.json')
    require(isinstance(base, list) and len(base) == 1000, 'Batch inventory must contain 1000 images')
    require([item['index'] for item in base] == list(range(1000)), 'Batch inventory order differs')
    require(len({h.name_of(item) for item in base}) == 1000, 'Duplicate inventory filenames')
    list_path = SOURCE / 'batches/batch-006.txt'
    immutable_list_bytes = list_path.read_bytes()
    require(immutable_list_bytes.decode('utf-8-sig').splitlines() == [item['filename'] for item in base],
            'Batch inventory differs from immutable batch-006.txt')
    metadata_path = h.regular_under(DATASET / 'metadata.csv', DATASET)
    metadata_bytes = metadata_path.read_bytes()
    metadata = {row['图片']: row for row in h.csv_parts(metadata_bytes)['rows']}
    all_proposals, group_summaries, changes = [], [], []
    total_before = total_after = 0
    for group in range(1, 5):
        directory = BATCH / f'group-{group}'
        inventory = read(directory / 'inventory.json')
        proposals = read(directory / 'proposals.json')
        manifest = read(directory / 'manifest.json')
        summary = read(directory / 'summary.json')
        require(inventory == base[(group-1)*250:group*250], f'Group {group}: inventory differs from batch')
        require(isinstance(proposals, list) and len(proposals) == 250 and
                len({h.name_of(proposal) for proposal in proposals}) == 250,
                f'Group {group}: exactly 250 unique proposals are required')
        for key in ('labels_written_to_dataset', 'approval_flags_cleared', 'user_approved'):
            require(summary.get(key, 0) == 0, f'Group {group}: {key} must be zero')
        for key in ('pending_only', 'all_require_user_review'):
            require(summary.get(key, True) is True, f'Group {group}: proposals must remain pending')
        require(summary.get('canonical_dataset_written', False) is False,
                f'Group {group}: visual reviewer must not write canonical dataset')
        require(isinstance(manifest.get('full'), list) and len(manifest['full']) == 125,
                f'Group {group}: exactly 125 full pages are required')
        require(isinstance(manifest.get('roi'), list), f'Group {group}: missing ROI manifest')
        full_by_local = {}
        full_paths = []
        for page in manifest['full']:
            path = evidence_path(page['path'], directory)
            require(Path(path).parent == directory / 'full', f'Group {group}: misplaced full page')
            full_paths.append(path)
            require(isinstance(page['locals'], list) and len(page['locals']) == 2,
                    f'Group {group}: each full page must cover two inventory images')
            for local in page['locals']:
                require(type(local) is int and 0 <= local < 250 and local not in full_by_local,
                        f'Group {group}: duplicated/invalid full-page local index')
                full_by_local[local] = path
        require(len(set(full_paths)) == 125 and set(full_by_local) == set(range(250)),
                f'Group {group}: incomplete full image coverage')
        roi_by_local = {local: {} for local in range(250)}
        for entry in manifest['roi']:
            local, box_index = entry['local'], entry['box_index']
            require(type(local) is int and 0 <= local < 250 and type(box_index) is int,
                    f'Group {group}: invalid ROI index')
            require(box_index not in roi_by_local[local] and
                    entry['filename'] == inventory[local]['filename'],
                    f'Group {group}: duplicate/mismatched ROI entry')
            path = evidence_path(entry['page'], directory)
            require(Path(path).parent == directory / 'roi', f'Group {group}: misplaced ROI page')
            roi_by_local[local][box_index] = path
        roi_paths = sorted({path for pages in roi_by_local.values() for path in pages.values()})
        opened_full = opened_pages(summary, 'actual_opened_full_pages', full_paths, directory)
        opened_roi = opened_pages(summary, 'actual_opened_roi_pages', roi_paths, directory)
        group_before = group_after = group_changed = group_scene_changed = 0
        for local, (baseline, proposal) in enumerate(zip(inventory, proposals)):
            name = baseline['filename']
            context = f'Group {group}, {name}'
            require((proposal['filename'], proposal['index']) == (name, baseline['index']),
                    f'{context}: proposal order/index differs from inventory')
            require(proposal.get('scene_seen') is True, f'{context}: scene was not seen')
            box_indices = [box['box_index'] for box in baseline['boxes']]
            require(len(box_indices) == len(set(box_indices)) and
                    proposal.get('roi_boxes_seen') == box_indices and
                    set(roi_by_local[local]) == set(box_indices), f'{context}: incomplete box_index coverage')
            require(isinstance(proposal.get('evidence'), list) and proposal['evidence'],
                    f'{context}: missing evidence')
            source_image = DATASET / 'images' / baseline['meta']['split'] / name
            evidence = {evidence_path(path, directory, source_image) for path in proposal['evidence']}
            require({full_by_local[local], *roi_by_local[local].values()} <= evidence,
                    f'{context}: evidence must include full scene and every existing-box ROI')
            require(proposal.get('expected_image_sha256') == baseline['image_sha256'] and
                    proposal.get('expected_label_sha256') == baseline['label_sha256'],
                    f'{context}: proposal SHA256 differs from inventory')
            flags = proposal.get('flags')
            require(isinstance(flags, dict) and set(flags) == set(FLAGS) and
                    all(type(value) is str and value in ('0', '1') for value in flags.values()),
                    f'{context}: four scene flags must be string 0/1 values')
            require(proposal.get('action') in ACTIONS, f'{context}: invalid action')
            require(proposal.get('confidence') in ('high', 'uncertain') and
                    type(proposal.get('scene_certain')) is bool,
                    f'{context}: invalid confidence/scene certainty')
            require(isinstance(proposal.get('reason'), str) and proposal['reason'].strip(),
                    f'{context}: missing visual reasoning')
            require(all(proposal.get(key, '1') == '1'
                        for key in ('label_review_required', 'scene_review_required')) and
                    proposal.get('user_approved', False) is False and
                    not str(proposal.get('annotation_status', '')).startswith(('reviewed_', 'negative_confirmed')),
                    f'{context}: proposal claims final approval')
            require(metadata.get(name) == baseline['meta'], f'{context}: dataset metadata differs from snapshot')
            split = baseline['meta']['split']
            image_path = h.regular_under(DATASET / 'images' / split / name, DATASET)
            label_path = h.regular_under(DATASET / 'labels' / split / (Path(name).stem + '.txt'), DATASET)
            original = label_path.read_bytes()
            require(h.digest(image_path.read_bytes()) == baseline['image_sha256'] and
                    h.digest(original) == baseline['label_sha256'] and
                    original == baseline['label_text'].encode('utf-8'),
                    f'{context}: actual image/label differs from inventory SHA256')
            old_boxes = h.label_boxes(original, boundary_tolerance=1e-6)
            require(len(old_boxes) == len(baseline['boxes']), f'{context}: inventory box count differs from label')
            final = replacement_label(proposal, baseline) if proposal['action'] == 'replace' else original
            final_boxes = h.label_boxes(final, boundary_tolerance=1e-6)
            require(flags['No Ball'] == ('0' if final_boxes else '1'),
                    f'{context}: No Ball must be 1 for zero final boxes, otherwise 0')
            # Occluded is a visual judgment. A box touching an edge does not
            # establish that the ball is truncated, so no geometry-derived flag.
            before_count, after_count = len(old_boxes), len(final_boxes)
            group_before += before_count
            group_after += after_count
            label_changed = original != final
            scene_changed = any(flags[key] != baseline['meta'][key] for key in FLAGS)
            group_changed += label_changed
            group_scene_changed += scene_changed
            if label_changed:
                changes.append(dict(filename=name, boxes_before=before_count, boxes_after=after_count))
        all_proposals.extend(proposals)
        total_before += group_before
        total_after += group_after
        group_summaries.append(dict(
            group=group, images=250, boxes=group_before, boxes_after=group_after,
            full_pages=len(opened_full), roi_pages=len(opened_roi),
            actions=dict(Counter(proposal['action'] for proposal in proposals)),
            flags={key: sum(proposal['flags'][key] == '1' for proposal in proposals) for key in FLAGS},
            uncertain=sum(proposal['confidence'] == 'uncertain' for proposal in proposals),
            priority=sum(proposal['confidence'] == 'uncertain' or proposal['action'].startswith('needs_')
                         for proposal in proposals),
            labels_changed=group_changed, scene_rows_changed=group_scene_changed))
    require([proposal['filename'] for proposal in all_proposals] == [item['filename'] for item in base],
            'Combined proposals do not exactly match batch inventory order')
    priority = [proposal['filename'] for proposal in all_proposals
                if proposal['confidence'] == 'uncertain' or proposal['action'].startswith('needs_')]
    priority_path = SOURCE / 'batches/batch-006-priority.txt'
    priority_bytes = ('\n'.join(priority) + ('\n' if priority else '')).encode('utf-8')
    if priority_path.exists():
        require(priority_path.read_bytes() == priority_bytes,
                'Existing batch-006-priority.txt differs; refusing to overwrite it')
    summary = dict(
        images=1000, boxes=total_before, boxes_after=total_after,
        full_pages=sum(group['full_pages'] for group in group_summaries),
        roi_pages=sum(group['roi_pages'] for group in group_summaries), groups=group_summaries,
        actions=dict(Counter(proposal['action'] for proposal in all_proposals)),
        uncertain=sum(proposal['confidence'] == 'uncertain' for proposal in all_proposals),
        priority=len(priority), labels_changed=len(changes), changed_labels=changes,
        scene_rows_changed=sum(group['scene_rows_changed'] for group in group_summaries),
        flags={key: sum(proposal['flags'][key] == '1' for proposal in all_proposals) for key in FLAGS},
        all_require_user_review=True, user_approved=0, labels_written_to_dataset=0,
        approval_flags_cleared=0, no_ball_matches_final_box_count=True,
        occluded_basis='visual_proposals_including_confirmed_edge_truncation; no_geometry_inference',
        review_policy=dict(path=str(HERE / 'review-policy.json'),
                           sha256=h.digest(input_bytes[HERE / 'review-policy.json']), policy=policy),
        dataset_metadata_sha256=h.digest(metadata_bytes),
        input_sha256={str(path): h.digest(data) for path, data in input_bytes.items()},
        immutable_batch_list_sha256=h.digest(immutable_list_bytes))
    # Finish every check before any output. Do not collect a moving input set.
    require(all(path.read_bytes() == data for path, data in input_bytes.items()) and
            metadata_path.read_bytes() == metadata_bytes and list_path.read_bytes() == immutable_list_bytes,
            'Inputs changed during collection; no outputs written')
    if not priority_path.exists():
        h.save_exclusive(priority_path, priority_bytes)
    for path, data in ((BATCH / 'proposals.json', json_bytes(all_proposals)),
                       (BATCH / 'summary.json', json_bytes(summary))):
        if path.exists():
            old = path.read_bytes()
            if old != data:
                h.atomic_replace(path, data, old)
        else:
            h.save_exclusive(path, data)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
