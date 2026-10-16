# Repro #4 — Schema & partition evolution: proving nothing was rewritten

**Goal:** rename a column, add a column, and re-partition a *live* table, then check
what actually happened on disk. Module 03's recap promises Iceberg does this "without
rewriting a byte, and field IDs are the trick" — this is where that gets verified
rather than asserted. The concrete version of Module 04.

## Stack
docker-spark-iceberg (catalog `demo`). One table: `db.evolve`, partitioned by
`days(event_ts)` with **no separate date column** — that absence is the point of
hidden partitioning.

## Run
```bash
just m04-evolve
# or manually:
docker exec spark-iceberg spark-sql -f /tmp/04_setup.sql   # build, insert 6, evolve x3, insert 2
docker exec spark-iceberg python3 /tmp/04_evolve.py
```

## What the setup does

6 rows over 3 days (3 data files, one per day). Then three evolutions, back to back:

1. `ALTER TABLE ... RENAME COLUMN user_name TO customer`
2. `ALTER TABLE ... ADD COLUMN region string`
3. `ALTER TABLE ... ADD PARTITION FIELD bucket(4, id)`

Then 2 more rows, written under the new schema and the new partition spec.

## Measured result (these become the module hooks)

**Snapshot IDs are regenerated on every run — never hardcode them. Everything below
is stable across runs.**

### 1. Field IDs are stable; names are not

```
schema-id=0  ->  1:id, 2:event_ts, 3:user_name, 4:amt
schema-id=1  ->  1:id, 2:event_ts, 3:customer,  4:amt
schema-id=2  ->  1:id, 2:event_ts, 3:customer,  4:amt, 5:region
```

Field id **3** kept its id and changed name `user_name` → `customer`. `region` arrived
as a **new** id 5, so the 6 rows already on disk simply have no column with that id —
a reader returns NULL for them without touching the files.

### 2. Evolving the table wrote no data at all

```
2 snapshots, BOTH appends:
  op=APPEND  added-data-files=3  added-records=6     <- the first insert
  op=APPEND  added-data-files=1  added-records=2     <- the second insert
```

The rename, the added column and the re-partition created **zero snapshots between
them**. They only wrote a new `metadata.json`. This is the headline number: *three
schema/partition changes, no data written.*

### 3. The old files still carry the OLD column name

```
spec_id=1  rows=2  partition event_ts_day=2026-07-04
    1:id, 2:event_ts, 3:customer,  4:amt, 5:region
spec_id=0  rows=2  partition event_ts_day=2026-07-01
    1:id, 2:event_ts, 3:user_name, 4:amt
spec_id=0  rows=2  partition event_ts_day=2026-07-02
    1:id, 2:event_ts, 3:user_name, 4:amt
spec_id=0  rows=2  partition event_ts_day=2026-07-03
    1:id, 2:event_ts, 3:user_name, 4:amt
```

**The strongest demonstration in the module.** Three parquet files on disk still say
`user_name` inside them. The table says `customer`. `SELECT customer` returns all 8 rows.
Nobody rewrote anything — the reader resolves columns by **field id 3**, so the name
stored in the file is never consulted. A rename is free precisely because the name was
never load-bearing.

### 4. Two partition layouts, one table

```
spec-id=0  ->  event_ts_day=day(field 2)
spec-id=1  ->  event_ts_day=day(field 2), id_bucket_4=bucket[4](field 1)

3 data file(s) still under spec-id 0
1 data file(s) now  under spec-id 1
```

Re-partitioning did **not** rewrite the existing files into the new layout. Old data
keeps spec 0, new writes use spec 1, and the planner reads across both. That is why a
re-partition is instant and free on a table of any size — the cost is deferred to
compaction (Module 05), not paid at ALTER time.

### 5. Hidden partitioning still prunes — across both specs

```
full scan plans           : 4 data file(s)
filter one day of event_ts: 1 data file(s)   -> skipped 3 of 4
```

The query filters `event_ts`. There is no partition column to filter — Iceberg maps the
predicate through `days(event_ts)` itself. No `dt=` column to maintain, no chance of the
partition column drifting out of sync with the real timestamp, and no query that
silently full-scans because someone forgot to add the partition predicate.

**Final state:** 8 rows across 4 files, 3 schemas, 2 partition specs.

## Notes / gotchas

- `event_ts` is `timestamptz`, so any pyiceberg `row_filter` literal needs an explicit
  ISO-8601 offset (`'2026-07-02T00:00:00+00:00'`) or `bind()` raises "Missing zone offset".
- The three spec-0 files share a filename prefix and differ only by partition directory —
  print the partition, not the basename, or they look like one file repeated.
- `plan_files()` can yield the same file more than once; de-duplicate by `file_path`
  before counting or inspecting.
