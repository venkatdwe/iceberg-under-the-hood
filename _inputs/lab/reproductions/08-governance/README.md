# Repro #8 — 4,441 bytes to delete five

**Goal:** put a price on the Module 03 choice rather than restating it. Delete the
same row from a copy-on-write table and a merge-on-read table, and measure what
each actually cost: bytes written per byte of real change, files a reader must
merge afterwards, and what stays on disk. The concrete version of Module 08.

## Stack
docker-spark-iceberg (catalog `demo`). Two tables, `db.gov_cow` and `db.gov_mor`,
identical but for `write.delete.mode` — so the strategy is the only variable.
5,000 rows with a 200-byte payload, large enough that rewriting a file is visibly
expensive.

## Run
```bash
just m08-cost
# or manually:
docker exec spark-iceberg spark-sql -f /tmp/08_setup.sql
docker exec spark-iceberg spark-sql -f /tmp/08_delete.sql
docker exec spark-iceberg python3   /tmp/08_measure.py
```

## Measured result (these become the module hooks)

**Byte totals drift a few bytes between runs (parquet compression). The ratios and
counts do not.**

### The headline: one row deleted, 833 rewritten

```
rows actually deleted:      1
rows rewritten to do it:    833
data files rewritten:       1
bytes written:              4,441        (~5.4 bytes per row on disk)

-> 822x amplification by bytes
-> 833x amplification by rows
```

**The unit of rewrite is a file, not a row.** Deleting one row rewrote the 834 rows
that happened to share its file. This is the number to lead with: nobody chooses
822× write amplification, they choose copy-on-write and get it.

### Read amplification is the other side of the same coin

```
bytes written per delete:   1,431   (vs 4,441 for copy-on-write)
delete files now live:      3   over 6 data files
scan tasks that must merge: 3 of 6
```

Merge-on-read made the write **three times cheaper** and handed the reader a job:
half the scan tasks now merge tombstones before returning a row, on **every query**,
until compaction applies them (Module 05).

Neither number is "the cost". The cost is that you pay one of them, and the choice
decides which — the same shape of trade as Modules 03, 06 and 07.

### A delete never shrinks storage

```
copy-on-write  live 6 files / 27,016 bytes  + 1 superseded file still referenced
merge-on-read  live 6 files / 26,996 bytes  + 0 superseded files
```

The rewritten file is kept for the snapshots that cite it. Storage falls only at
expiry (Module 06) — which is why "we deleted a lot of data and the bill didn't
move" is the expected outcome, not a billing error.

### The metrics worth alerting on

```
                      copy-on-write   merge-on-read
data files                        6               6
avg file size                 4,502           4,499  bytes
delete files                      0               3
snapshots retained                2               4
```

None of these is a cost by itself. They are the **inputs** to one: small average
file size means planning overhead (Module 05), delete files mean read
amplification, retained snapshots mean storage you are paying for (Module 06).
Cost governance is watching the inputs, because the bill arrives a month after the
decision that caused it.

## Notes / gotchas

- **A CoW delete commits as `overwrite`, not `delete`.** Filtering snapshots for
  `op == "delete"` finds nothing and looks like the delete never happened. The
  measure script accepts either.
- **`added-records` is the honest amplification number**, not `deleted-records`:
  833 rows were *written back*, 834 were in the original file. Quoting the wrong
  one overstates the cost by one row and invites a correction.
- **The 200-byte payload matters.** With a narrow schema the files are so small
  that rewriting one looks free, and the amplification ratio collapses into noise.
- `write.distribution-mode = none` keeps Spark from reshuffling on write, so the
  file layout — and therefore which rows share a file — stays predictable.
- pyiceberg's snapshot `operation` is an **enum**; compare `op.value`.
- `plan_files()` can yield the same file more than once — de-duplicate by
  `file_path` before counting bytes, or the totals come out inflated.
- Spark SQL metadata tables do **not** resolve against this REST catalog; read
  metadata through pyiceberg.

## Not demonstrated in this lab

- **Money.** There is no cloud bill here, and inventing dollar figures would be the
  one thing this repro must not do. The measurable quantities are bytes written,
  files opened, and files retained; converting those to spend is arithmetic the
  viewer does with their own provider's rates, and the module should say so rather
  than pick a number.
- **Maintenance compute cost.** Compaction and expiry consume cluster time, but at
  6,000-row scale every job finishes in seconds and any timing shown would be
  meaningless. Teach it from the work performed — files rewritten, rows sorted —
  which this repro does measure.
