-- Lab repro #90 — DuckDB reads the Iceberg metadata tree, no catalog, no Spark.
--
-- Prereq: repro #1's table exists (01-metadata-tree/01_create.sql), lab is up.
-- Run:    duckdb -f walk.sql
--
-- The point: one engine, plain SQL, reads every layer Iceberg writes — and
-- shows the SAME fact at two altitudes (raw Avro blob -> decoded bound).

LOAD iceberg;
LOAD httpfs;

-- MinIO is S3-compatible; path-style, no TLS, creds from docker-compose.yml.
CREATE OR REPLACE SECRET ms (
  TYPE s3, KEY_ID 'admin', SECRET 'password',
  ENDPOINT 'localhost:9000', URL_STYLE 'path', USE_SSL false, REGION 'us-east-1'
);

-- No catalog in play: we point at a PATH, so DuckDB must find the newest
-- metadata.json itself. Spark+REST writes no version-hint.text, hence:
SET unsafe_enable_version_guessing = true;


-------------------------------------------------------------------------------
SELECT '=== 0. Snapshots — the commit lineage ===' AS step;
-------------------------------------------------------------------------------
SELECT sequence_number, snapshot_id, timestamp_ms
FROM iceberg_snapshots('s3://warehouse/db/events')
ORDER BY sequence_number;


-------------------------------------------------------------------------------
SELECT '=== 1. The manifest tree — which manifest points at which data file ===' AS step;
-------------------------------------------------------------------------------
SELECT manifest_sequence_number       AS seq,
       regexp_extract(manifest_path, '([^/]+)$') AS manifest,
       status, content, record_count,
       regexp_extract(file_path, '([^/]+)$')     AS data_file
FROM iceberg_metadata('s3://warehouse/db/events')
ORDER BY seq;


-------------------------------------------------------------------------------
SELECT '=== 2. LEVEL 1 PRUNE — partition bounds, decoded ===' AS step;
-- These live in the manifest list. A query filtered on event_date can discard
-- an entire manifest here, before any data file is considered.
-------------------------------------------------------------------------------
SELECT regexp_extract(manifest_path, '([^/]+)$') AS manifest,
       partition_field_name, partition_field_transform,
       partition_field_type, lower_bound, upper_bound
FROM iceberg_partition_stats('s3://warehouse/db/events');


-------------------------------------------------------------------------------
SELECT '=== 3. LEVEL 2 PRUNE — per-file, per-column bounds ===' AS step;
-- Manifest entries. Discards whole data files without opening them.
-------------------------------------------------------------------------------
SELECT regexp_extract(file_path, '([^/]+)$') AS data_file,
       column_name, value_count, null_value_count, lower_bound, upper_bound
FROM iceberg_column_stats('s3://warehouse/db/events')
ORDER BY data_file, column_name;


-------------------------------------------------------------------------------
SELECT '=== 4. THE SAME FACT, RAW — read the Avro manifest undecoded ===' AS step;
-- lower_bounds is map(field_id -> blob). Field 2 = event_date.
-- \x97P little-endian int32 = 20631 days since epoch = 2026-06-27,
-- which is exactly what step 3 printed as a DATE.
-------------------------------------------------------------------------------
SELECT status,
       data_file.record_count,
       data_file.file_size_in_bytes AS bytes,
       data_file.lower_bounds       AS raw_lower_bounds
FROM read_avro('s3://warehouse/db/events/metadata/*-m0.avro');


-------------------------------------------------------------------------------
SELECT '=== 5. LEVEL 3 PRUNE — row-group zonemaps inside one Parquet file ===' AS step;
-- NOTE the anomaly: `user` reports NULL min/max here, yet step 3 gave
-- alice/bob. Iceberg's manifest carries bounds the Parquet footer does not
-- expose — which is WHY level-2 pruning works without opening the file.
-------------------------------------------------------------------------------
SELECT row_group_id AS rg, path_in_schema AS col, num_values,
       stats_min, stats_max, compression, encodings
FROM parquet_metadata('s3://warehouse/db/events/data/event_date=2026-06-27/*.parquet')
ORDER BY rg, col;


-------------------------------------------------------------------------------
SELECT '=== 6. The prune, end to end ===' AS step;
-------------------------------------------------------------------------------
SELECT count(*) AS rows_read, min(event_date) AS lo, max(event_date) AS hi
FROM iceberg_scan('s3://warehouse/db/events')
WHERE event_date = DATE '2026-06-28';
