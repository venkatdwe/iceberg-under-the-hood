# Repro #1 — Inspect the Metadata Tree

**Goal:** build a tiny Iceberg table and read every layer of the real metadata tree from object storage, by hand.

## Stack
docker-spark-iceberg (Spark + Iceberg REST catalog + MinIO). Catalog `demo` (REST → `s3://warehouse/`).

## Steps
1. `docker compose up -d` in `_inputs/repos/docker-spark-iceberg/`
2. `docker cp 01_create.sql spark-iceberg:/tmp/ && docker exec spark-iceberg spark-sql -f /tmp/01_create.sql`
   - Tiny table: 4 rows, partitioned by `event_date`, **two separate INSERTs** (each = its own snapshot/manifest/data file).
3. Inspect physical files: `docker exec mc mc ls -r minio/warehouse/`
4. Dump metadata.json: `docker exec mc mc cat minio/warehouse/db/events/metadata/0000N-*.metadata.json | python3 -m json.tool`
5. Walk the tree: `docker cp 03_walk.py spark-iceberg:/tmp/ && docker exec spark-iceberg python3 /tmp/03_walk.py`

> Note: querying Spark metadata tables (`demo.db.events.snapshots`) over the **REST fixture** throws `BadRequestException: Malformed request` in this image — a known REST-fixture quirk. Use the `03_walk.py` (pyiceberg + pyarrow) path instead; it reads the metadata files directly.

## What the files looked like (measured numbers — these become course hooks)

Physical layout in MinIO for one 4-row table:
```
data/event_date=2026-06-27/00000-...-00001.parquet   1.2 KiB   (insert #1)
data/event_date=2026-06-28/00000-...-00001.parquet   1.2 KiB   (insert #2)
metadata/00000-*.metadata.json   919 B    (after CREATE — empty table)
metadata/00001-*.metadata.json   1.9 KiB  (after insert #1)
metadata/00002-*.metadata.json   2.8 KiB  (after insert #2)   <- catalog pointer points here
metadata/snap-1959...-*.avro     4.3 KiB  (manifest list, snapshot 1)
metadata/snap-4894...-*.avro     4.4 KiB  (manifest list, snapshot 2)
metadata/c2f6121a-*-m0.avro      7.3 KiB  (manifest, insert #1)
metadata/80a75c57-*-m0.avro      7.3 KiB  (manifest, insert #2)
```

Key observations:
- **3 metadata.json** for a 2-insert table — every commit writes a NEW one; the catalog pointer moves 00000 → 00001 → 00002. That's the metadata-log / atomic-commit lineage.
- **Reuse proven:** snapshot #2's manifest list references TWO manifests — the new one (`80a75c57`) AND insert #1's (`c2f6121a`), re-referenced, not rewritten.
- **Level-1 prune (manifest list):** partition bounds are LE int32 days-since-epoch — `\x98P` = 20632 = 2026-06-28, `\x97P` = 20631 = 2026-06-27.
- **Level-2 prune (manifest entries):** per-file `lower/upper_bounds` keyed by **field-id** (event_date, user, amt).
- **Parquet footer:** 1 row group, 2 rows; `event_date` → `PLAIN_DICTIONARY` (low-cardinality), others `PLAIN`; all columns `ZSTD` (uniform compression — table property `write.parquet.compression-codec=zstd`).
- **Pruning proof:** `WHERE event_date='2026-06-28'` → planner kept **1 of 2** files (the 06-27 manifest skipped at level 1).

## The hook (for Module 01)
"A 4-row table produced 9 files: 2 data, 3 metadata.json, 2 manifest lists, 2 manifests. The query engine answered a filtered query by reading ~2 rows of partition ranges and never opening the file that didn't match."
