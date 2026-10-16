# Repro #10 — 42 bytes to delete a row, and the client that cannot read it

**Goal:** measure what spec v3 actually changes, and what it costs you to adopt
it today. Two tables identical but for `format-version`, the same row deleted
from each. Then the part nobody puts in the announcement post: whether the rest
of your stack can read the result. The concrete version of Module 10.

## Stack
docker-spark-iceberg (catalog `demo`, Spark 3.5.6, Iceberg 1.9.0, pyiceberg
0.9.1). Tables `db.dv_v2` / `db.dv_v3` for the delete comparison and
`db.lineage_demo` for row lineage. 500 rows, 50-byte payload — small on purpose,
because the interesting number is the size of the DELETE, not of the table.

## Run
```bash
just m10-specv3
# or manually:
docker exec spark-iceberg spark-sql -f /tmp/10_setup.sql
docker exec spark-iceberg spark-sql -f /tmp/10_delete.sql
docker exec spark-iceberg python3   /tmp/10_measure.py     # layers 1-4
docker exec spark-iceberg spark-sql -f /tmp/10_lineage.sql # row lineage
```

## Measured result (these become the module hooks)

**Byte totals drift a few bytes between runs (parquet compression). The ratios,
counts and failures do not.**

### The headline: 42 bytes against ~1,416

**BYTE COUNT VARIES BY RUN.** The v2 position-delete file measured 1,417 bytes on
2026-09-08 and 1,416 on 2026-09-25 — same script, same row. The v3 figure (42),
the ratio (33.7x), the row count (499) and the file count (6) have all been
stable. Re-check the v2 number against the capture before quoting it in
narration; a one-byte drift will put the script out of step with the screen.

Identical tables, identical row deleted, both merge-on-read. The only difference
is `format-version`:

| | bytes written | delete files | position deletes | pyiceberg 0.9.1 read |
|---|---|---|---|---|
| **v2** | **1,416** | 1 | 1 | OK — 499 rows |
| **v3** | **42** | 1 | 1 | **ValueError: 'PUFFIN' is not a valid FileFormat** |

**33.7x smaller.** Both record one delete file and one position delete — the
difference is entirely in *what that file is*: a position-delete parquet against
a Puffin deletion vector.

### `write.delete.mode` is load-bearing

A first probe created a v3 table **without** it, deleted a row, and produced
**zero delete files**: the default is still copy-on-write, so the whole data file
was rewritten and no deletion vector ever appeared.

v3 alone does not give you deletion vectors. v3 **plus merge-on-read** does. This
is worth teaching because "we upgraded to v3" is exactly what a team would say
before measuring that nothing had changed.

### The better headline: support is per-client, and not in the order you would guess

Three readers, one v3 table:

| reader | v2 | v3 (deletion vector) |
|---|---|---|
| Spark 3.5.6 / Iceberg 1.9.0 | writes it | **writes it** |
| pyiceberg 0.9.1 | OK — 499 rows | **FAILS** — `ValueError: 'PUFFIN' is not a valid FileFormat` |
| DuckDB 1.5.2 | OK — 499 rows | **OK — 499 rows** |

The Python client **in the same container that wrote the table** cannot read it,
because a deletion vector is a Puffin file and that version's `FileFormat` enum
has no entry for it. Meanwhile DuckDB — a different project, on nobody's
roadmap for this — reads it correctly.

Note the 499. DuckDB did not merely tolerate the deletion vector, it **applied**
it: the table holds 500 rows with one deleted. A reader that ignored the vector
would have returned 500 and been silently wrong, which is the worse failure.

So the lesson is not "Python is behind" and not "v3 is risky". It is that v3
support is **per-client and does not follow seniority** — the format's own
reference Python library trails a third-party analytical engine. You cannot infer
it; you have to test the specific clients you run. **A table one tool writes and
another cannot open is worse than not adopting yet**, and which tools those are
is not predictable from a version number.

### Row lineage: allocated, but not usable as an identity

A plain v3 table, 200 rows, no updates and no deletes:

```
                  rows   distinct _row_id   min   max   data files
pre-compaction     200          6             0   166        6
post-compaction    200          1           200   200        1
```

**The distinct-id count equals the data-file count, exactly, in both states.**
The spec derives a row's id from its file's `first_row_id` plus the row's
position within that file; the read path here returns only the file-level value,
so every row in a file comes back with the same id. After compaction that is 200
rows all reporting id 200.

What *is* working is the allocation — ids advance correctly (0..166 across six
files, then exactly 200, which is precisely the 200 rows consumed).

### CORRECTION 2026-09-29 — the sequence number is file-level too

An earlier note here claimed `_last_updated_sequence_number` "behaves as
specified: 2 for an updated row, 1 for untouched ones". Measured on a fresh
six-file v3 table, that is **not** what happens:

```
BEFORE UPDATE            seq 1 -> 200 rows
UPDATE 3 rows (id <= 3)  seq 1 -> 167 rows
                         seq 2 ->  33 rows
```

Three rows were updated; **33 rows report the new sequence number** — one whole
data file's worth (200 rows across 6 files). The update rewrote the file
copy-on-write and the sequence number moved for every row in it.

So the sequence number tells you *"something in this file changed"*, not *"this
row changed"* — the same file-level granularity as `_row_id`. It is directionally
useful for change detection at file scale, and it is not a row-level signal.

Do not narrate it as the column that works correctly where `_row_id` does not.
Both collapse to the file; `_row_id` is simply the more obvious of the two.

So: **allocation works, the read path has not caught up.** Row lineage is the
feature most often cited when arguing for v3, and in this version you cannot yet
build anything on it. That is the second independent instance of the same
lesson, on the same table format, in one module.

## Notes / gotchas

- **`write.delete.mode = merge-on-read` is required** to get a deletion vector at
  all. See above — this is the single most likely way to "adopt v3" and measure
  no change.
- **Do not compare across table geometries.** An earlier draft compared v3's 42
  bytes against module 08's 1,431, which is a different table with a different
  payload. `db.dv_v2` exists specifically so the comparison is like-for-like.
- **pyiceberg 0.9.1 raises on any scan of a table with a deletion vector**, so
  `03_measure.py` catches and REPORTS that failure rather than letting it end the
  run. The client failing IS the measurement, not a bug in the repro.
- **`_row_id` is a Spark metadata column**, not readable through pyiceberg, so the
  lineage layer is SQL rather than Python like the others.
- Row lineage was measured on its own table (`db.lineage_demo`) with no updates
  or deletes, so nothing else can be blamed for the result.

## Not demonstrated in this lab

- **The variant type.** Listed in this module's registry concepts but not probed
  here. Confirm against 1.9.0 before claiming anything about it; do not assume it
  ships because the spec defines it — this repro has now found two v3 features
  where the spec and the implementation disagree.
- **Whether other engines read the v3 table.** Only Spark (writes) and pyiceberg
  (fails) were tested. DuckDB 1.5.2 attaches this catalog — see
  `reproductions/14-interop/FINDINGS.md` — so it is the obvious next reader to
  try, and would sharpen "ecosystem lag" from a single data point into a range.
- **Deletion-vector compaction.** Whether `rewrite_data_files` applies deletion
  vectors the way it applies position deletes was not measured here.

## Upgrading an EXISTING v2 table — measured 2026-09-25

The setup scripts set `format-version` and `write.delete.mode` at CREATE time.
The question a viewer actually has is how to turn this on for a table they
already have. Probed on a scratch table (`db.dv_probe`, created and dropped):

```sql
ALTER TABLE db.dv_probe SET TBLPROPERTIES (
  'format-version'    = '3',
  'write.delete.mode' = 'merge-on-read'
);
```

Then a single `DELETE ... WHERE id = 500` against 1,000 rows in 6 files:

```
seq=2 op=delete
     added-delete-files = 1
     added-dvs          = 1     <- a real deletion vector
     total-data-files   = 6     <- unchanged, nothing rewritten
```

So the in-place upgrade works and the very next delete writes a vector.

**Gotcha found while probing.** A first attempt used 3 rows, which Spark wrote
as 3 separate data files. Deleting one row then reported
`deleted-data-files = 1` and `total-delete-files = 0` — no vector at all. That
is correct behaviour, not a failed upgrade: when every row in a file is
deleted, Iceberg drops the whole file rather than writing a vector describing
it. Any demonstration of deletion vectors needs several rows per data file, or
it silently measures the wrong thing.
