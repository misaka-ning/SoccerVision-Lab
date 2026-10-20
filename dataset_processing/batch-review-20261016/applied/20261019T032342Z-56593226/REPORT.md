# Independent handoff audit

PASS

- accepted398_zero_skipped_failed_zero_approved: PASS
- audit_baseline_and_proposals_equal_frozen: PASS
- before_current398_rows_equal_frozen_meta: PASS
- before_sha_equals_batch8_approval_after: PASS
- live_metadata_sha_equals_apply_result: PASS
- 8398_rows_order_headers_rawheader_BOM_preserved: PASS
- all_record_endings_preserved: PASS
- all8000_outside_raw_records_preserved: PASS
- all8000_completed_rows_not_reset: PASS
- 398_images_sha_unchanged: PASS
- all398_label_backups_equal_frozen_and_stage: PASS
- exactly6_candidate_label_bytes_equal_independent_and_registry: PASS
- all392_other_labels_precise_bytes_unchanged: PASS
- 360_to360_boxes_54empty_NoBall_exact: PASS
- all398_double11_pending_expected_status: PASS
- only_fourflags_status_note_reviewfields_change_counts_provenance_preserved: PASS
- all398_prior_note_prefixes_preserved_exact_note_appended: PASS
- all398_scene_flags_match_frozen_proposals_77rows_changed: PASS
- global8000done398pending_no_mixed: PASS
- apply_result_labels_changed_6: PASS
- all_collected_frozeninput_SHA_still_match: PASS

{
  "accepted": 398,
  "skipped": 0,
  "failed": 0,
  "labels_changed": 6,
  "labels_unchanged": 392,
  "boxes_before": 360,
  "boxes_after": 360,
  "empty_labels": 54,
  "scene_rows_changed": 77,
  "outside_raw_preserved": 8000,
  "completed": 8000,
  "pending": 398,
  "flags": {
    "Small": 64,
    "Occluded": 55,
    "Blurred": 330,
    "No Ball": 54
  },
  "changed_columns": [
    "Blurred",
    "Occluded",
    "Small",
    "annotation_status",
    "label_review_note"
  ]
}
