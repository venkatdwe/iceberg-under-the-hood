# Repro #90 — DuckDB reads the Iceberg metadata tree (no catalog, no Spark)

**Goal:** prove that a single embedded engine, using plain SQL, can read *every*
layer Iceberg writes — and can show the same fact at two altitudes: the raw Avro
blob and the decoded bound. This is the "we open the files" demo.

## Stack
Same lab as repro #1 (docker-spark-iceberg → MinIO). **DuckDB v1.5.2** on the host,
extensions `iceberg` (11fea8ed), `avro` (a73b60d), `httpfs`. Spark is used only to
*create* the table; every read below is DuckDB.

## Steps
1. Lab up: `docker compose up -d` in `_inputs/repos/docker-spark-iceberg/`
2. Table exists: run `01-metadata-tree/01_create.sql` (see repro #1)
3. `duckdb -f walk.sql`

## Findings

### 1. Reads work by PATH — no catalog required
`iceberg_snapshots()`, `iceberg_metadata()`, `iceberg_partition_stats()`,
`iceberg_column_stats()`, `iceberg_scan()` all accept `s3://warehouse/db/events`
directly. Because Spark+REST writes no `version-hint.text`, DuckDB must locate the
newest `metadata.json` itself — hence `SET unsafe_enable_version_guessing = true`.

### 2. Writes DO require a catalog — and the failure is the lesson
```
ATTACH '…/wh' AS ice (TYPE ICEBERG);
  -> AUTHORIZATION_TYPE is 'oauth2', yet no 'secret' was provided
ATTACH '…/wh' AS ice (TYPE ICEBERG, AUTHORIZATION_TYPE 'none');
  -> Missing 'endpoint' option for Iceberg attach
```
There is **no local filesystem catalog**. Commits are catalog-mediated (REST / Glue /
S3 Tables). By contrast `ATTACH 'ducklake:…'` writes locally with zero ceremony.
That contrast *is* the ACID story: **in Iceberg the catalog is the commit authority**
(pairs directly with repro #2's real compare-and-swap conflict).

### 3. Three levels of pruning, all visible in SQL
| Level | Function | Discards | Evidence |
|---|---|---|---|
| 1 | `iceberg_partition_stats` | whole **manifests** | `event_date` lower=upper=`2026-06-27` vs `2026-06-28`, transform `identity`, type `DATE` |
| 2 | `iceberg_column_stats` | whole **data files** | per-file bounds: `id` 1–2 / 3–4, `amt` 10.0–20.0 / 30.0–40.0, `user` alice–bob / alice–carol |
| 3 | `parquet_metadata` | **row groups** | 1 row group, 2 values/col, ZSTD, `event_date` → `PLAIN_DICTIONARY`, others `PLAIN` |

### 4. The two-altitude shot (the money demo)
`read_avro()` on the manifest returns `lower_bounds` as `map(field_id → blob)`:
```
{1=\x01\x00\x00\x00\x00\x00\x00\x00, 2=\x97P\x00\x00, 3=alice, 4=…$@}
```
- field 2 = `event_date`, `\x97P` = LE int32 `20631` = **2026-06-27**
- field 4 = `amt`, `\x00\x00\x00\x00\x00\x00$@` = LE double **10.0**

…and `iceberg_column_stats` prints that same field as a decoded `2026-06-27`.
Raw bytes and human-readable bound, side by side, in one session. **Independently
confirms repro #1's hand-decoded `\x97P` finding using a different tool.**

### 5. Anomaly worth teaching — Iceberg stats ≠ Parquet stats
For the `user` column, `parquet_metadata()` reports `stats_min/max = NULL`, yet
`iceberg_column_stats()` reports `alice`/`bob`. **Iceberg's manifest carries bounds
the Parquet footer does not expose here** — which is exactly why level-2 pruning can
discard a file without opening it. Common assumption ("Iceberg metadata is just a
copy of the Parquet footers") is refuted by this table.
⚠️ Root cause not yet pinned down (writer-side string-stats suppression is the
hypothesis). **Verify before teaching as fact.**

### 6. Determinism confirmed
Re-running repro #1 two months later (2026-08-28) reproduced repro #1's file layout
**byte-for-byte**: 9 files — 2 data (1.2 KiB each), 3 `metadata.json` (919 B / 1.9 KiB
/ 2.8 KiB), 2 manifest lists (4.3 / 4.4 KiB), 2 manifests (7.3 KiB each). Only UUIDs
and snapshot ids differ.

## Hooks
- "One embedded engine, no catalog, no cluster — reading every layer of an Iceberg
  table with SQL. Here's the raw byte, and here's the same byte decoded."
- "Iceberg needs a catalog to *write*. DuckLake doesn't. That difference is the
  entire ACID story — and it's the control point everyone's actually fighting over."

## Course placement
Primary: **Module 01 (The Metadata Tree)** as the DuckDB-native inspection path,
alongside pyiceberg `03_walk.py`. Level-1/2/3 table feeds **Module 07 (Partitioning,
Clustering & Data Skipping)**. The catalog-authority contrast feeds **Module 02**
and **Module 11 (Catalogs & the REST Spec)**.
