# Repro #0 — Why Iceberg, in one contrast

**Goal:** show the difference between "the directory is the table" and "the
metadata is the table" by doing the same thing to both and measuring the result.
The whole argument for a table format, without a slide.

## Stack
docker-spark-iceberg (catalog `demo`, Spark 3.5.6, Iceberg 1.9.0) plus the
lab's `mc` container for object storage. Requires the lab up: `just lab-up`.

## Run
```bash
docker cp 01_hive_style.py spark-iceberg:/tmp/00_hive_style.py
docker exec spark-iceberg python3 /tmp/00_hive_style.py
bash 02_iceberg.sh          # runs on the HOST, uses docker exec
```

## Measured result 2026-09-29

Both halves start identically: **300 rows across 6 data files.** Then one more
Parquet file appears where the table's data lives — in step 1 by an ordinary
append, in step 2 by copying a file straight into the prefix.

| | rows before | rows after | files before | files after |
|---|---|---|---|---|
| **Hive-style** (a directory of Parquet) | 300 | **351** | 6 | 12 |
| **Iceberg** (`db.ice_demo`) | 300 | **300** | 6 | 7 |

The Hive-style table grew by 51 rows because a file changed. Nothing approved
it, and nothing recorded it — there is no catalog to record it in. A job that
dies halfway leaves a table that is halfway.

The Iceberg table did not move. The stray file is sitting in its data
directory right now and is not part of the table, because no commit references
it. Reachability is decided by metadata, not by `ls`.

**That is the entire pitch for a table format, and it is two numbers.**

## Why this is the right opening demo
- It needs no prior vocabulary — no snapshots, no manifests, no catalog API.
- It is the one comparison the rest of the course keeps paying off: every later
  module is a consequence of "the metadata decides what the table is".
- It is measured in this lab, so it is not a claim borrowed from a vendor page.

## Notes / gotchas
- **`DROP TABLE` leaves the data files behind.** A re-run would then count stale
  files from the previous run and the "one file appeared" step reads as a no-op.
  `02_iceberg.sh` clears the object-storage prefix with `mc rm --recursive`
  before creating the table. This cost one confusing run before it was spotted.
- **The stray filename must be unique per run** for the same reason — copying
  over an existing stray file leaves the count unchanged.
- Spark cannot write to `s3://` directly in this image (Iceberg uses its own
  S3FileIO), which is why step 2 plants the file with `mc` rather than Spark.
- Step 1 writes to container-local `/tmp`, not object storage, deliberately:
  the point is a plain directory with no catalog anywhere near it.
