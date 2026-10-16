-- Repro #6, step 2 — expire the old snapshots.
--
-- retain_last => 1 keeps only the current snapshot. That is deliberate for a
-- teaching lab and WRONG for production: the retention window is exactly how
-- far back you can time travel, and setting it to one commit means you cannot
-- roll back at all. Production picks a window from its recovery needs (often
-- days), not from a desire for a tidy file listing.
--
-- older_than is set far in the future so the demo does not have to wait; in
-- production this is what expresses the window.
--
-- Returns: deleted_data_files_count, deleted_position_delete_files_count,
--          deleted_equality_delete_files_count, deleted_manifest_files_count,
--          deleted_manifest_lists_count, deleted_statistics_files_count

CALL demo.system.expire_snapshots(
  table      => 'db.lifecycle',
  older_than => TIMESTAMP'2099-01-01 00:00:00',
  retain_last => 1
);
