# Repro #3 — CoW vs MoR: what a delete physically writes

**Goal:** delete the *same* row from two identical tables that differ only in `write.delete.mode`,
and inspect what each strategy wrote. The concrete version of Module 03.

## Stack
docker-spark-iceberg (catalog `demo`). Two tables: `db.events_cow`, `db.events_mor`.

## Run
```bash
just m03-deletes
# or manually:
docker exec spark-iceberg spark-sql -f /tmp/03_setup.sql   # build both, insert 3 rows, DELETE user='bob'
docker exec spark-iceberg python3 /tmp/03_compare.py
```

## Measured result (these become the module hooks)

Both tables: 3 rows inserted (alice, bob, carol in one data file), then `DELETE WHERE user='bob'`.
Both readers end up seeing **2 rows**. What they *wrote* to get there is opposite:

**Copy-on-write** (`write.delete.mode=copy-on-write`):
```
DELETE commit summary: added-data-files=1  deleted-data-files=1  deleted-records=3  total-delete-files=0
files: [ADDED  ][DATA] records=2     <- a brand-new file with the survivors
       [DELETED][DATA] records=3     <- the original 3-row file, dropped
```
→ The entire data file was **rewritten** to remove one row. No delete files. **Reads stay clean; the write paid.**

**Merge-on-read** (`write.delete.mode=merge-on-read`):
```
DELETE commit summary: added-delete-files=1  added-position-deletes=1  total-delete-files=1
files: [ADDED][DATA]            records=3   <- original file UNTOUCHED
       [ADDED][POSITION-DELETE] records=1   <- a tiny *-deletes.parquet tombstone
```
→ The data file was **left alone**; a 1-row **position-delete** tombstone says "row N of file X is dead."
**The write was cheap; every read must now merge the tombstone** (until compaction removes it).

## The takeaways
- **The cost doesn't vanish — it moves.** CoW front-loads cost to write time (clean reads). MoR defers cost to every read (cheap writes).
- **Position delete** = "file X, row Y is dead" (what Spark `DELETE` wrote here). **Equality delete** = "any row where `user='bob'`" — even cheaper to write (no need to locate the row), but reads re-evaluate the predicate. Streaming upserts favor equality deletes.
- **MoR debt accumulates:** every delete adds a file readers must merge. `total-delete-files` climbing = read latency creeping up → that's the compaction trigger (Module 05), and what v3 deletion vectors (Module 10) make cheaper.

## The hook (for Module 03)
"To delete one row, copy-on-write rewrote the entire data file into a new one. Merge-on-read
wrote a four-kilobyte tombstone and didn't touch the data. Same delete, same answer — and that
single choice quietly decides whether your write is slow or your every read is."

> Note: builds `db.events_cow` and `db.events_mor` (independent of `db.events`).
