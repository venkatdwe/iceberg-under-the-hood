# Repro #6 — Snapshot & metadata lifecycle: paying Module 05's bill

**Goal:** start exactly where Module 05 ended — compacted, with eight replaced data
files still sitting in object storage and *more* total bytes than before — then run
each cleanup procedure and measure what it reclaims, what it does not, and what it
costs you. The concrete version of Module 06.

## Stack
docker-spark-iceberg (catalog `demo`). One table: `db.lifecycle`, built by the same
eight trickle commits plus compaction as repro #5, so the two modules describe the
same table at two points in its life.

## Run
```bash
just m06-expire
# or manually:
docker exec spark-iceberg spark-sql -f /tmp/06_setup.sql      # 8 commits + compact
docker exec spark-iceberg spark-sql -f /tmp/06_expire.sql     # expire_snapshots
docker exec spark-iceberg spark-sql -f /tmp/06_manifests.sql  # rewrite_manifests
docker exec spark-iceberg python3   /tmp/06_measure.py
docker exec spark-iceberg spark-sql -f /tmp/06_meta.sql       # metadata cleanup ON
```

## Measured result (these become the module hooks)

**Snapshot IDs regenerate on every run — never hardcode them.**

### 1. Nine snapshots become one — permanently

```
CALL expire_snapshots(older_than => ..., retain_last => 1)
-> deleted_data_files=8  deleted_manifest_files=8  deleted_manifest_lists=8
```

The eight `append` snapshots from the trickle are gone. Not archived — **gone**. The
measure script then shows 2 snapshots rather than 1, because `rewrite_manifests`
commits its repack as a snapshot of its own.

### 2. The bytes Module 05 could not reclaim

Module 05 ended with 8 replaced files still on disk (9,864 bytes) alongside the
compacted one, and total storage *higher* than before compaction. After expiry:

```
live data files: 1  (~1,423 bytes)
of those, present in object storage: 1
```

`expire_snapshots` is what actually deleted them. **Compaction stops referencing;
expiry deletes.** That is the whole relationship between the two modules.

### 3. The rows survive. The history does not.

```
current snapshot: 8 rows
an expired snapshot id: ValueError — Snapshot not found
```

This is the point worth dwelling on. Every row is still readable — expiry never
touches live data. What it destroys is the ability to go *back*. `retain_last => 1`
in this lab means you cannot roll back a single commit.

**Retention is a recovery decision, not housekeeping.** The window you keep is
exactly how far back you can undo a bad write, and choosing it by how tidy the file
listing looks is choosing your recovery posture by accident.

### 4. Manifests accumulate too

```
manifests in the current snapshot: 1   (was 9)
optimized-m-....avro
```

Every commit writes a manifest, and the planner reads that list on **every query**
before opening any data. `rewrite_manifests` repacked 9 into 1.

### 5. Metadata bloat — the one nobody turns on

```
metadata.json versions retained: 11        (with 2 snapshots)
write.metadata.delete-after-commit.enabled = false
write.metadata.previous-versions-max       = 100 (default)
```

Expiring snapshots does **not** prune `metadata.json` files. It is a separate
mechanism and it is **off by default**, so a busy table quietly accumulates a
metadata directory that can outgrow the data it describes.

Turn it on and commit once:

```
write.metadata.delete-after-commit.enabled = true
write.metadata.previous-versions-max       = 3
-> 12 metadata.json files became 4
```

Note it prunes on the **next commit**, not retroactively — setting the property on an
idle table does nothing until something writes.

## Notes / gotchas

- **`remove_orphan_files` cannot run in this lab.** The Spark image has no
  `org.apache.hadoop.fs.s3a.S3AFileSystem`, so the procedure fails with
  `UnsupportedFileSystemException: No FileSystem for scheme "s3"` regardless of the
  `location` argument. That is an environment limit, not an Iceberg one — cover
  orphan removal conceptually rather than faking a demo. (It also refuses any
  `older_than` interval under 24 hours by design, since concurrent writers may be
  mid-commit on files that look orphaned.)
- `expire_snapshots` returns six counts:
  `deleted_data_files, deleted_position_delete_files, deleted_equality_delete_files,
  deleted_manifest_files, deleted_manifest_lists, deleted_statistics_files`.
- `retain_last => 1` is correct for a teaching lab and **wrong for production**. Set
  the window from recovery needs.
- pyiceberg's snapshot `operation` is an enum — compare `op.value`, not the object.
- The measure script must run **after** the procedures; its layers report the state
  they leave behind, not a live before/after.
