#!/usr/bin/env python3
"""Independently verify metadata-only approval without project audit helpers."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
from pathlib import Path

from independent_statistics import parse_label


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def parts(raw):
    text = raw.decode('utf-8-sig')
    lines = io.StringIO(text, newline='').readlines()
    reader = csv.reader(iter(lines), strict=True)
    values, raw_records, endings = [], [], []
    start = 0
    for value in reader:
        end = reader.line_num
        record = ''.join(lines[start:end])
        raw_records.append(record.encode('utf-8'))
        endings.append('\r\n' if record.endswith('\r\n') else '\n' if record.endswith('\n') else '\r' if record.endswith('\r') else '')
        values.append(value)
        start = end
    headers = values[0]
    rows = [dict(zip(headers, value)) for value in values[1:]]
    assert all(len(value) == len(headers) for value in values[1:])
    assert len(headers) == len(set(headers))
    return {'headers': headers, 'rows': rows, 'records': raw_records, 'endings': endings,
            'bom': raw.startswith(b'\xef\xbb\xbf')}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--audit', type=Path, required=True)
    p.add_argument('--snapshot', type=Path, required=True)
    args = p.parse_args()
    root = args.dataset.absolute()
    audit = args.audit.absolute()
    snapshot_raw = args.snapshot.read_bytes()
    snapshot = json.loads(snapshot_raw)
    before_raw = (audit / 'before/metadata.csv').read_bytes()
    after_raw = (root / 'metadata.csv').read_bytes()
    before = parts(before_raw)
    after = parts(after_raw)
    before_rows = {r['图片']: r for r in before['rows']}
    after_rows = {r['图片']: r for r in after['rows']}
    records = json.loads((audit / 'approved-records.json').read_text(encoding='utf-8'))
    result = json.loads((audit / 'result.json').read_text(encoding='utf-8'))
    inventory = json.loads((audit / 'before/inventory.json').read_text(encoding='utf-8'))
    selected_names = [r['filename'] for r in snapshot['records']]
    selected = set(selected_names)
    allowed = {'annotation_status', 'scene_review_required', 'label_review_required', 'label_review_note'}
    changes = Counter()
    checks = {}
    checks['fresh_snapshot_equals_before_inventory'] = snapshot == inventory
    checks['fresh_snapshot_sha_anchors_before_metadata'] = snapshot['metadata_sha256'] == sha(before_raw)
    checks['result_anchors_before_and_after_metadata'] = (result['metadata_before_sha256'] == sha(before_raw) and result['metadata_after_sha256'] == sha(after_raw))
    checks['398_snapshot_unique_and_approved_order'] = (len(selected_names) == len(selected) == 398 and selected_names == [r['filename'] for r in records])
    checks['total8398_order_headers_BOM_preserved'] = (len(before['rows']) == len(after['rows']) == 8398 and
        [r['图片'] for r in before['rows']] == [r['图片'] for r in after['rows']] and
        before['headers'] == after['headers'] == snapshot['headers'] and before['bom'] == after['bom'] and
        before['records'][0] == after['records'][0])
    checks['all_record_line_endings_preserved'] = before['endings'] == after['endings']
    outside = [(i, r) for i, r in enumerate(before['rows'], 1) if r['图片'] not in selected]
    checks['outside8000_raw_records_preserved'] = len(outside) == 8000 and all(before['records'][i] == after['records'][i] for i, r in outside)
    metadata_safe = True
    snapshot_matches_before = True
    media_safe = True
    note_safe = True
    semantic_safe = True
    approved_safe = True
    label_errors = []
    counts = Counter()
    confirmation = '2026-10-19 用户明确确认本批 label 和场景均已人工审核完成。'
    for index, baseline in enumerate(snapshot['records']):
        name = baseline['filename']
        old = before_rows[name]
        new = after_rows[name]
        detail = records[index]
        snapshot_matches_before &= baseline['meta'] == old
        changed = {k for k in before['headers'] if old[k] != new[k]}
        changes.update(changed)
        metadata_safe &= not (changed - allowed)
        metadata_safe &= all(new[k] == old[k] for k in before['headers'] if k not in allowed)
        metadata_safe &= new['scene_review_required'] == new['label_review_required'] == '0'
        note_safe &= new['label_review_note'] == (old['label_review_note'] + ' ' + confirmation).strip()
        ip = root / 'images' / new['split'] / name
        lp = root / 'labels' / new['split'] / (Path(name).stem + '.txt')
        ih = sha(ip.read_bytes())
        lh = sha(lp.read_bytes())
        media_safe &= ih == baseline['image_sha256'] and lh == baseline['label_sha256']
        boxes, error = parse_label(lp)
        if error:
            label_errors.append({'filename': name, 'error': error})
        expected = ('reviewed_annotation' if boxes else 'negative_confirmed') if not error else 'reviewed_excluded'
        semantic_safe &= new['annotation_status'] == expected
        semantic_safe &= (bool(boxes) and new['No Ball'] == '0') or (boxes == [] and new['No Ball'] == '1')
        counts[new['annotation_status']] += 1
        approved_safe &= (detail['image_sha256'] == ih and detail['label_sha256'] == lh and detail['annotation_status'] == new['annotation_status']
                          and detail['previous_status'] == old['annotation_status'] and detail['No Ball'] == new['No Ball']
                          and detail['box_count'] == (None if error else len(boxes)) and detail['label_validation_error'] == error)
    checks['398_snapshot_metadata_equals_before_rows'] = snapshot_matches_before
    checks['only_status_note_reviewflags_changed_fourflags_split_provenance_counts_preserved'] = metadata_safe
    checks['398_prior_notes_preserved_exact_confirmation_appended'] = note_safe
    checks['398_images_labels_match_fresh_snapshot_SHA256'] = media_safe
    checks['398_dual00_status_matches_actual_labels_NoBall'] = semantic_safe and not label_errors
    checks['approved_records_match_actual_media_and_metadata'] = approved_safe
    checks['344positive54negative0excluded'] = dict(counts) == {'reviewed_annotation': 344, 'negative_confirmed': 54}
    checks['result_declares_zero_media_scene_writes_and_actual_counts'] = (result['count'] == 398 and result['counts'] == dict(counts) and
        result['images_written'] == result['labels_written'] == result['scene_values_written'] == 0)
    reviewed = sum(r['scene_review_required'] == r['label_review_required'] == '0' for r in after['rows'])
    pending = sum(r['scene_review_required'] != '0' or r['label_review_required'] != '0' for r in after['rows'])
    checks['dataset8398_dual00_zero_pending'] = reviewed == 8398 and pending == 0
    checks['metadata_stable_during_verification'] = (root / 'metadata.csv').read_bytes() == after_raw
    failures = [name for name, passed in checks.items() if not passed]
    verification = {
        'status': 'PASS' if not failures else 'FAIL', 'success': not failures,
        'reviewer': 'independent_final_dataset_audit', 'canonical_dataset_written': False,
        'created_at_utc': datetime.now(timezone.utc).isoformat(), 'checks': checks, 'failures': failures,
        'metrics': {'images_approved': 398, 'counts': dict(counts), 'outside_raw_preserved': 8000,
                    'dataset_reviewed': reviewed, 'dataset_pending': pending, 'changed_column_counts': dict(changes)},
        'metadata_before_sha256': sha(before_raw), 'metadata_after_sha256': sha(after_raw), 'snapshot_sha256': sha(snapshot_raw),
    }
    (audit / 'verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    report = '\n'.join([
        '# 第9批用户确认批准独立核验', '',
        '结论：' + verification['status'] + '。独立脚本仅写本审核证据，未写 datasets。', '',
        '- 本批398张：344张有球通过、54张无球通过、0张排除。',
        '- 398张原图与 label 的 SHA-256 均与用户审核后的 fresh snapshot 一致。',
        '- 仅 annotation_status、两项 review flag、label_review_note 改变；四类分类、split、框数元数据、来源字段及其余字段保持。',
        '- 原备注完整保留，并追加2026-10-19用户明确完成审核的确认。',
        '- 批外8000条 CSV 原始记录逐字节保持；8398条顺序、表头、UTF-8 BOM 与每条记录换行保持。',
        '- 全数据8398张两项审核标记均为0；无待审核记录。',
        '- reviewed_excluded 继续作为已审核保留样本，不能当作无球负例。', '',
        '详情见 verification.json。' if not failures else '失败项目：' + '、'.join(failures), '',
    ])
    (audit / 'REPORT.md').write_text(report, encoding='utf-8')
    print(json.dumps(verification, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
