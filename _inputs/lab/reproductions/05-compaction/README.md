# Repro #5 — The small-file problem, priced

**Goal:** create the small-file problem the way it actually happens, measure what
it costs, compact it away, and then look at what compaction leaves behind. The
concrete version of Module 05.

## Stack
docker-spark-iceberg (catalog `demo`). One table: `db.trickle`, **unpartitioned on
purpose** — the small-file problem is caused by commit rate, not by layout, and a
partitioned table would let a viewer blame the partitioning instead.

## Run
```bash
just m05-compact
# or manually:
docker exec spark-iceberg spark-sql -f /tmp/05_setup.sql     # 8 separate INSERTs
docker exec spark-iceberg spark-sql -f /tmp/05_compact.sql   # CALL rewrite_data_files
docker exec spark-iceberg python3 /tmp/05_measure.py
```

## What the setup does

Eight separate `INSERT`s of one row each. Nobody chooses to write 1-row files —
they arrive from a feed that commits often, and **every commit writes at least one
file**. Eight commits stand in for eight minutes of a stream that never stops.

## Measured result (these become the module hooks)

**Snapshot IDs regenerate on every run — never hardcode them. Everything below is
stable, ±5 bytes on the compacted file.**

### 1. Eight commits, eight files

```
op=append  added=1  deleted=0  total-data-files=1
op=append  added=1  deleted=0  total-data-files=2
...                                            8
op=replace added=1  deleted=8  total-data-files=1
```

### 2. The cost is overhead, not data — the headline number

```
file 1: 1 row   1223 bytes        file 5: 1 row   1236 bytes
file 2: 1 row   1230 bytes        file 6: 1 row   1236 bytes
file 3: 1 row   1230 bytes        file 7: 1 row   1237 bytes
file 4: 1 row   1235 bytes        file 8: 1 row   1237 bytes
-> 8 files, 9864 bytes, for 8 rows
```

Roughly **1,230 bytes to store one row of four small columns.** A parquet file
carries a footer, a schema and per-column metadata whatever it holds, so a 1-row
file is almost entirely overhead. This is the number to lead with.

### 3. Compaction is a commit, not a mutation

```
op=replace  added-data-files=1  deleted-data-files=8  total-data-files=1
```

`rewrite_data_files` read the current files, wrote a replacement, and swapped the
pointer — the same commit protocol as any write (Module 02). Nothing was edited in
place, because nothing in Iceberg ever is.

Defaults used: **bin-pack** strategy, **512 MB** target file size, minimum **5**
input files before it acts. Eight 1-row files clear the minimum and fit one output
file with room to spare.

### 4. Same rows, one file

```
file 1: 8 rows  1422 bytes
-> 9864 bytes became 1422: 6.9x smaller, 86% of the original was per-file overhead
```

The data never changed. Only the number of files did.

### 5. The bill compaction leaves behind — the counterintuitive one

```
old data files still in object storage: 8 of 8
time travel to the pre-compaction snapshot still returns 8 rows
storage right now = 9864 + 1422 = 11286 bytes
```

**Compaction temporarily increases storage.** It stops *referencing* the old files;
it does not delete them, and it must not — the pre-compaction snapshot is still a
valid snapshot, and time travel to it still works. Reclaiming those bytes is
`expire_snapshots` plus `remove_orphan_files`, which is Module 06. Anyone who runs
compaction expecting the storage bill to drop that night is in for a surprise.

## Notes / gotchas

- `rewrite_data_files` is a **stored procedure** (`CALL demo.system....`), not DDL.
  It returns `(rewritten_data_files_count, added_data_files_count, rewritten_bytes,
  failed_data_files_count)`.
- It **does nothing** below `min-input-files` (default 5) and returns `0 0 0 0`. An
  early probe with 3 files looked like a failure and was not — check the count
  before assuming the procedure is broken.
- Spark SQL metadata tables (`db.trickle.files`) do **not** resolve against this REST
  catalog — Spark reads `db.trickle.files` as a namespace path and the request 400s.
  Read metadata through pyiceberg instead, as every repro here does.
- pyiceberg's snapshot `operation` is an **enum**; compare `op.value == "replace"`,
  not the object itself.
- The pre-compaction state is reachable without bookkeeping: the REPLACE snapshot's
  `parent_snapshot_id` **is** the before state, so one script can scan both sides.
