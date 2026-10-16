-- Walk the metadata tree top-down using Iceberg's metadata tables.
-- Each query maps to one layer: snapshots -> manifest list -> manifests -> files.
--
-- ⚠️ DOES NOT WORK on this lab's REST fixture: Spark metadata-table queries
--    (demo.db.events.snapshots) throw `BadRequestException: Malformed request`.
--    Use the pyiceberg inspector instead:  `just m01-inspect`  (04_inspect.py)
--    — it exposes the SAME tables with every column. This .sql is kept as a
--    reference for what the queries look like on a Hive/JDBC/Glue catalog.

-- SNAPSHOTS  (each commit = one snapshot; points to one manifest list)
SELECT committed_at, snapshot_id, parent_id, operation FROM demo.db.events.snapshots ORDER BY committed_at;
SELECT * FROM demo.db.events.snapshots ORDER BY committed_at;

-- HISTORY  (which snapshot was current when)
SELECT made_current_at, snapshot_id, is_current_ancestor FROM demo.db.events.history;

-- MANIFESTS  (the manifest LIST: 1 row per manifest + partition min/max ranges)
--   look at partition_summaries -> lower_bound / upper_bound = the level-1 prune
SELECT path, length, added_snapshot_id, added_data_files_count, partition_summaries
FROM demo.db.events.manifests;

-- FILES  (inside the manifests: 1 row per data file + per-column stats = the level-2 prune)
--   record_count, file_size, and lower_bounds/upper_bounds per column id
SELECT file_path, record_count, file_size_in_bytes, partition, lower_bounds, upper_bounds
FROM demo.db.events.files;

-- METADATA LOG  (the chain of metadata.json files the catalog pointer moved across)
SELECT * FROM demo.db.events.metadata_log_entries;

-- Prove the pruning: this should read ONLY the 06-28 file, not both
-- (run with EXPLAIN to see the scan / pushed filters)
EXPLAIN SELECT * FROM demo.db.events WHERE event_date = DATE'2026-06-28';
