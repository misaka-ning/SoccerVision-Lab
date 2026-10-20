#!/usr/bin/env python3
"""Protect human edits, exact source data, and reviewed exclusion semantics."""
import contextlib
import copy
import csv
import io
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import approve_reviewed_batch as a


def csv_bytes(rows):
    out = io.StringIO(newline=''); w = csv.DictWriter(out, fieldnames=rows[0], lineterminator='\r\n')
    w.writeheader(); w.writerows(rows)
    return b'\xef\xbb\xbf'+out.getvalue().encode()


with tempfile.TemporaryDirectory(prefix='football-approve-') as t:
    root = Path(t); rows = []
    for i in range(6):
        r = {'图片': f'frame_{i}.png', 'Small': '0', 'Occluded': '0', 'Blurred': '0', 'No Ball': '1' if i==1 else '0',
             'split': 'train', 'annotation_status': 'uncertain_bbox' if i==2 else 'needs_manual_bbox_annotation',
             'scene_review_required': '1', 'label_review_required': '1', 'label_review_note': '保留原备注',
             'source_video': '旧源.avi', 'auto_box_count': '3', 'preserved_box_count': '1', 'extra_column': '保留未知字段'}
        rows.append(r)
        ip = root/'images/train'/r['图片']; lp = root/'labels/train'/f'frame_{i}.txt'
        ip.parent.mkdir(parents=True, exist_ok=True); lp.parent.mkdir(parents=True, exist_ok=True)
        ip.write_bytes(f'image{i}'.encode())
        lp.write_bytes(b'' if i in [1,3] else b'0 0.01 0.5 0.1 0.2\n' if i==4 else b'0 0.5 0.5 0.2 0.2\n')
    mp = root/'metadata.csv'; original = csv_bytes(rows); mp.write_bytes(original)
    image_list = root/'batch.txt'; image_list.write_text(''.join(r['图片']+'\n' for r in rows[:5]))
    snapshot = root/'snapshot.json'; a.snapshot(root, image_list, snapshot, 5); b = a.h.read_json(snapshot)
    _, _, updates, details = a.plan(root, b)
    assert [r['annotation_status'] for r in details] == ['reviewed_annotation', 'negative_confirmed', 'reviewed_excluded', 'reviewed_excluded', 'reviewed_excluded']
    for key in rows[0]:
        changed = copy.deepcopy(rows); changed[0][key] = 'val' if key=='split' else changed[0][key]+'-new'
        mp.write_bytes(csv_bytes(changed))
        try: a.plan(root, b)
        except (ValueError, KeyError): pass
        else: raise AssertionError('Unprotected metadata field: '+key)
    mp.write_bytes(original)
    for path in [root/'images/train/frame_0.png', root/'labels/train/frame_0.txt']:
        before = path.read_bytes(); path.write_bytes(before+b'changed')
        try: a.plan(root, b)
        except ValueError: pass
        else: raise AssertionError('Unprotected image or label')
        path.write_bytes(before)
    # The CLI must honor the exact QLockFile protocol used by the GUI.
    lock_list = root/'outer-lock.json'; lock_list.write_text(json.dumps([str(root/'labels/train/frame_0.txt')+'.review.lock']))
    approval_command = [sys.executable, str(Path(a.__file__).resolve()), 'approve', '--dataset', str(root), '--snapshot', str(snapshot),
                        '--expect-count', '5', '--expect-excluded', '3', '--audit-dir', str(root/'blocked-audit'),
                        '--review-date', '2026-10-19', '--apply']
    blocked = subprocess.run([str(a.SHARED/'qt_review_lock_runner'), '--lock-list', str(lock_list), '--', *approval_command], capture_output=True)
    assert blocked.returncode==73, (blocked.returncode, blocked.stdout, blocked.stderr)
    assert mp.read_bytes()==original and not (root/'blocked-audit').exists()
    before_files = {str(p):p.read_bytes() for p in root.glob('*/*/*') if p.is_file()}
    applied = subprocess.run([str(root/'audit') if part == str(root/'blocked-audit') else part
                              for part in approval_command], capture_output=True)
    assert applied.returncode == 0, (applied.stdout, applied.stderr)
    result = json.loads(applied.stdout)
    after = a.h.csv_parts(mp.read_bytes()); assert after['bom']
    assert after['records'][-1] == a.h.csv_parts(original)['records'][-1]
    assert (root/'audit/before/metadata.csv').read_bytes() == original
    for r in after['rows'][:5]:
        assert r['label_review_required'] == r['scene_review_required'] == '0'
        assert '2026-10-19 用户明确确认本批 label 和场景均已人工审核完成。' in r['label_review_note']
        old = next(x for x in rows if x['图片']==r['图片'])
        for key in old:
            if key not in ['annotation_status', 'label_review_required', 'scene_review_required', 'label_review_note']: assert r[key]==old[key]
    assert all(Path(p).read_bytes()==data for p,data in before_files.items())
    try: a.plan(root, b)
    except ValueError: pass
    else: raise AssertionError('Reapplying a stale approval snapshot was permitted')
    print(json.dumps({'all_metadata_fields_guarded':len(rows[0]), 'source_hash_guards':True, 'outside_raw_csv_preserved':True,
                      'scene_values_preserved':True, 'labels_images_untouched':True, 'exact_backup':True,
                      'excluded_not_negative':True, 'repeat_rejected':True, 'qt_lock_contention_no_writes':True,
                      'explicit_review_date_survives_locked_cli':True}, ensure_ascii=False))
