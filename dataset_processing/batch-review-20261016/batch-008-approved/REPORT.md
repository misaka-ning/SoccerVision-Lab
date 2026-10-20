# Independent handoff audit

PASS

- fresh_snapshot_equals_audit_before_inventory: PASS
- immutable_1000_order_snapshot_and_details: PASS
- metadata_after_anchored_by_result_sha: PASS
- total8398_order_headers_BOM_preserved: PASS
- all_record_line_endings_preserved: PASS
- outside_7398_raw_records_preserved: PASS
- 1000_images_labels_match_fresh_snapshot_sha: PASS
- only_status_note_reviewflags_changed_fourflags_provenance_counts_preserved: PASS
- 1000_prior_notes_preserved_exact_confirmation_appended: PASS
- 1000_dual00_status_consistent_with_labels_NoBall: PASS
- approved_records_match_actual_fresh_media: PASS
- 624_positive376_negative_zero_excluded: PASS
- result_declares_zero_media_scene_writes: PASS
- dataset_done8000_pending398_no_mixed: PASS

{
  "images_approved": 1000,
  "reviewed_annotation": 624,
  "negative_confirmed": 376,
  "reviewed_excluded": 0,
  "outside_raw_preserved": 7398,
  "dataset_done": 8000,
  "dataset_pending": 398,
  "changed_columns": [
    "annotation_status",
    "label_review_note",
    "label_review_required",
    "scene_review_required"
  ]
}
