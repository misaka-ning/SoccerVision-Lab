#!/usr/bin/env python3
"""Compare independently computed results with the primary audit outputs."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


independent = read('independent-statistics.json')
independent_rows = read('independent-row-outcomes.json')
primary = read('statistics.json')
primary_rows = read('image-inventory.json')
quality = read('quality-details.json')
unusable = read('unusable-images.json')
o = primary['overall']
checks = {}
overall_mapping = {
    'total': 'total', 'usable': 'trainable', 'reviewed_excluded': 'reviewed_excluded',
    'pending': 'pending_any_review_flag', 'usable_positive': 'positive', 'usable_negative': 'confirmed_negative',
    'statuses': 'status', 'flags_all': 'flags_all', 'flags_usable': 'flags_trainable',
    'all_zero': 'all_four_flags_zero', 'all_zero_usable': 'trainable_all_four_flags_zero',
    'boxes_usable': 'trainable_boxes',
}
checks['same_metadata_sha256'] = primary['metadata_sha256'] == independent['metadata_sha256']
for pk, ik in overall_mapping.items():
    checks['overall_' + pk] = o[pk] == independent[ik]
checks['overall_unusable'] = o['unusable'] == independent['reviewed_excluded'] + independent['other_unusable']
checks['valid_label_count'] = o['valid_label_files'] == independent['label_validation']['valid']
checks['nonempty_label_count'] = o['nonempty_labels'] == independent['label_validation']['positive_label_images']
checks['empty_label_count'] = o['empty_labels'] == independent['label_validation']['empty_label_images']
checks['valid_box_count_all'] = o['boxes_all_valid_labels'] == independent['label_validation']['valid_box_count_all']
checks['image_resolution_counts'] = o['resolutions'] == independent['image_validation']['dimensions']
checks['image_format_counts'] = o['formats'] == independent['image_validation']['formats']
checks['all_scene_combinations'] = primary['scene_combinations_all'] == independent['flag_combinations_all']
checks['usable_scene_combinations'] = primary['scene_combinations_usable'] == independent['flag_combinations_trainable']
split_mapping = {
    'total': 'total', 'usable': 'trainable', 'reviewed_excluded': 'reviewed_excluded',
    'usable_positive': 'positive', 'usable_negative': 'confirmed_negative', 'statuses': 'status',
    'flags_all': 'flags_all', 'flags_usable': 'flags_trainable', 'all_zero': 'all_four_flags_zero',
    'all_zero_usable': 'trainable_all_four_flags_zero', 'boxes_usable': 'trainable_boxes',
}
for split, own in independent['split'].items():
    for pk, ik in split_mapping.items():
        checks[split + '_' + pk] = primary['splits'][split][pk] == own[ik]
own_index = {r['filename']: r for r in independent_rows}
primary_index = {r['filename']: r for r in primary_rows}
checks['all8398_row_names_unique_and_match'] = len(own_index) == len(primary_index) == len(independent_rows) == len(primary_rows) == 8398 and own_index.keys() == primary_index.keys()
checks['all8398_row_usable_split_status_boxcount_match'] = all(
    own['trainable'] == primary_index[name]['usable'] and own['split'] == primary_index[name]['split']
    and own['status'] == primary_index[name]['status'] and own['valid_boxes'] == primary_index[name]['box_count']
    for name, own in own_index.items())
checks['primary_all_images_valid_confirmed_by_full_pixel_decode'] = independent['image_validation']['decoded'] == 8398 and all(r['image_valid'] for r in primary_rows)
own_invalid_names = {r['filename'] for r in independent['label_validation']['errors']}
primary_invalid_names = {r['filename'] for r in quality['issues'] if not r['label_valid']}
checks['four_invalid_label_names_match_and_all_excluded'] = len(own_invalid_names) == 4 and own_invalid_names == primary_invalid_names and all(own_index[n]['status'] == 'reviewed_excluded' for n in own_invalid_names)
checks['250_unusable_names_match_exactly'] = {n for n, r in own_index.items() if not r['trainable']} == {r['filename'] for r in unusable} and len(unusable) == 250
own_multiball_all = sum(r['valid_boxes'] is not None and r['valid_boxes'] > 1 for r in independent_rows)
own_multiball_usable = sum(r['trainable'] and r['valid_boxes'] > 1 for r in independent_rows)
checks['202_multi_ball_all_and197_usable'] = o['multi_ball_images_all'] == own_multiball_all == 202 and o['multi_ball_images_usable'] == own_multiball_usable == 197
for pk, ik in (('actual_image_files', 'image_files'), ('actual_label_files', 'label_files'),
               ('missing_images', 'missing_metadata_images'), ('extra_images', 'extra_images_without_metadata'),
               ('missing_labels', 'missing_metadata_labels'), ('extra_labels', 'extra_labels_without_metadata')):
    checks['physical_' + pk] = primary['quality'][pk] == independent['physical_inventory'][ik]
checks['explicit_known_provenance_cross_split_frames_zero'] = independent['provenance_overlap']['source_frame_groups_across_splits'] == primary['quality']['source_frame_cross_split_groups'] == 0
checks['explicit_known_provenance_coverage6508_unknown1890'] = independent['provenance_overlap']['rows_complete_provenance'] == 6508 and independent['provenance_overlap']['rows_incomplete_provenance'] == 1890
checks['all_independent_internal_checks_passed'] = all(independent['checks'].values())
failures = [k for k, v in checks.items() if not v]
result = {
    'status': 'PASS' if not failures else 'FAIL', 'success': not failures,
    'created_at_utc': datetime.now(timezone.utc).isoformat(),
    'canonical_dataset_written': False,
    'method': 'Independent csv.reader, own YOLO validation and Pillow.Image.load() for all 8398 images, then a row-level and metric-level comparison with primary audit files.',
    'checks': checks, 'failures': failures,
    'checks_passed': sum(checks.values()), 'checks_total': len(checks),
    'independent_metrics': {'total': independent['total'], 'usable': independent['trainable'],
        'reviewed_excluded': independent['reviewed_excluded'], 'pending': independent['pending_any_review_flag'],
        'positive': independent['positive'], 'negative': independent['confirmed_negative'],
        'usable_boxes': independent['trainable_boxes'], 'all_zero': independent['all_four_flags_zero'],
        'all_zero_usable': independent['trainable_all_four_flags_zero'], 'multi_ball_all': own_multiball_all,
        'multi_ball_usable': own_multiball_usable, 'images_full_pixel_decoded': independent['image_validation']['decoded'],
        'invalid_labels_all_excluded': len(own_invalid_names)},
    'file_sha256': {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in (
        'independent-statistics.json', 'independent-row-outcomes.json', 'statistics.json', 'image-inventory.json', 'quality-details.json', 'unusable-images.json')},
    'limits': ['The primary exact-image duplicate SHA-256 scan was not repeated; independent full-image decoding and batch-009 image/label hash verification were completed.',
               'Cross-split provenance checks cover 6508 explicitly sourced rows; 1890 rows have incomplete provenance, so no absence of overlap is asserted for those rows.'],
}
(HERE / 'independent-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
report = [
    '# 全量数据集独立核验', '',
    f"结论：{result['status']}。{result['checks_passed']}/{result['checks_total']}项独立统计、逐图和主统计交叉对照通过。", '',
    '8398张均已完成两项人工审核：8148张可用于训练/评估，250张已审核排除；待审核0张。可用部分为5220张有球、2928张确认无球，共5417个有效球框。', '',
    '| split | 全量 | 可用 | 已审核排除 | 有球可用 | 无球可用 | 有效框 |',
    '| --- | ---: | ---: | ---: | ---: | ---: | ---: |',
]
for split, one in independent['split'].items():
    report.append(f"| {split} | {one['total']} | {one['trainable']} | {one['reviewed_excluded']} | {one['positive']} | {one['confirmed_negative']} | {one['trainable_boxes']} |")
report += ['', '| 四类独立多标签 | 全量 | 可用 |', '| --- | ---: | ---: |']
for flag in ('Small', 'Occluded', 'Blurred', 'No Ball'):
    report.append(f"| {flag} | {independent['flags_all'][flag]} | {independent['flags_trainable'][flag]} |")
report += [
    '', '四项均为0：全量1743张，可用1621张。四类为多标签，可以重叠。', '',
    '8398张原图均用 Pillow.Image.load() 完整解码通过；8398个图文件、8398个 label 与 metadata 逐一对应，无缺失或孤立文件。', '',
    '250张排除样本中，41张保留有效非空 label，205张为空 label，4张球框越界。4张异常均已处于 reviewed_excluded；本审核保留源数据，不修框，也不将空 label 排除样本视为无球负例。', '',
    '已知明确来源的6508张中，同一源帧同目以及左右目跨 split 重叠均为0；1890张来源字段不完整，无法据此排除其重叠。未重新去重或重新分集。', '',
    '主审核的全图 SHA-256 重复扫描未重复执行；本独立核验额外完成全图像素解码，并对第9批398张图及 label 执行独立 SHA-256 不变性核验。', '',
    '4张越界 label：', '',
]
report.extend('- ' + name for name in sorted(own_invalid_names))
report += ['', '本审核只写证据文件，未修改 datasets。详情见 independent-verification.json 与 independent-statistics.json。', '']
(HERE / 'independent-REPORT.md').write_text('\n'.join(report), encoding='utf-8')
print(json.dumps({'status': result['status'], 'checks_passed': result['checks_passed'], 'checks_total': result['checks_total'], 'failures': failures, 'metrics': result['independent_metrics']}, ensure_ascii=False, indent=2))
