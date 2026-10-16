# Repro #7 — Clustering: same rows, same files, 6× the work

**Goal:** write one set of rows three different ways — scattered, sorted, z-ordered —
and measure how many files a point lookup has to open in each. Nothing about the
data changes. Only which rows share a file. The concrete version of Module 07.

## Stack
docker-spark-iceberg (catalog `demo`, Spark 3.5.6, Iceberg 1.9.0). One table:
`db.clustering`, **unpartitioned on purpose** — partitioning is Module 04's subject,
and adding it here would let a viewer credit the partition rather than the clustering.

## Run
```bash
just m07-cluster
# or manually:
docker exec spark-iceberg spark-sql -f /tmp/07_setup.sql
docker exec spark-iceberg python3   /tmp/07_load.py        # 6 scattered commits
docker exec spark-iceberg python3   /tmp/07_measure.py "scattered"
docker exec spark-iceberg spark-sql -f /tmp/07_sort.sql    # sort on customer_id
docker exec spark-iceberg python3   /tmp/07_measure.py "sorted"
docker exec spark-iceberg spark-sql -f /tmp/07_zorder.sql  # zorder(customer_id, amt)
docker exec spark-iceberg python3   /tmp/07_measure.py "z-ordered"
```

## What the setup does

Six commits of 1,000 rows. Each carries a slice of `id`, but customers from across
the whole range — the shape any feed produces when it is ordered by time rather than
by the column people filter on. `customer_id` and `amt` are independent of `id` and
of each other (different prime multipliers, mod 1000), so clustering one tells you
nothing about the other.

## Measured result (these become the module hooks)

**Byte sizes and snapshot ids regenerate on every run. The file counts and skip
percentages below are stable.**

### The headline: identical rows, 6 of 6 files vs 1 of 8

| layout | files | `customer_id = 500` | `amt = 500` |
|---|---|---|---|
| **scattered** (arrival order) | 6 | **opens 6 of 6** — skips 0% | opens 6 of 6 — skips 0% |
| **sorted** by `customer_id` | 8 | **opens 1 of 8** — skips 88% | opens 8 of 8 — skips 0% |
| **z-ordered** `(customer_id, amt)` | 8 | opens 8 of 8 — skips 0% | **opens 1 of 8** — skips 88% |

6,000 rows in every case. The planner opened nothing to decide this — it compared the
filter against each file's min/max and ruled files out before reading a byte.

### 1. Scattered: every file covers the whole column

```
1000 rows   customer_id   0..999   amt   0..999      (x6)
customer_id span per file: min 999, max 999   (column range is 0..999)
```

This is the number that makes the concept undeniable. **Every file's min/max spans
the entire column**, so every file *might* contain customer 500 and the planner
cannot rule out a single one. Pruning is working perfectly and buying nothing —
there is simply nothing in the stats to prune on.

Note the table is healthy by every Module 05 measure: 6 files, ~5.7 KB each, no
small-file problem. **File-count dashboards show this table as fine.**

### 2. Sorted: the same rows, narrow ranges

```
customer_id span per file: min 64, max 166   (was 999)
customer_id = 500  opens 1 of 8 files   (skips 7, 88%)
```

Sorting on `customer_id` collapses each file's range from ~999 to ~100. A customer
lookup now reads one file instead of six. **Row count identical, file count slightly
higher, six times less work.**

### 3. Z-order: measured, and not what the description implies

Z-ordering is usually described as balancing several columns so any of them prunes
reasonably. On this data it did not:

```
customer_id span per file: min 895, max 999   -> opens 8 of 8  (0% skipped)
amt         span per file: min  63, max 166   -> opens 1 of 8  (88% skipped)
```

It behaved as a **sort on `amt` alone**, leaving `customer_id` no better than
scattered. Verified across two file-size targets (8 KB and 20 KB) and two data shapes
(correlated and independent columns) — the result held every time.

This is worth teaching honestly rather than smoothing over: **z-order is a heuristic,
not a guarantee**, and whether it helps depends on cardinality, data distribution and
the implementation. The lesson is to measure your own table rather than trust the
label — which is a more useful takeaway than "z-order balances your columns" would
have been.

### 4. The trade is real either way

Sorted and z-ordered are mirror images: each is excellent for one column and useless
for the other. There is no arrangement that makes both filters fast, because a file
can only be sorted one way. **Clustering is choosing which query to favour** — the
same shape of decision as CoW vs MoR in Module 03 and retention in Module 06.

### 5. Clustering is a property of the last write, not a table mode

```
table sort-order: unsorted (writes are not ordered on arrival)
```

Even after two sort-based rewrites, the table's declared sort-order is still empty.
`rewrite_data_files` ordered the files it wrote; it did not tell the table to keep
doing so. New writes arrive scattered again, and the clustering decays until the next
rewrite. Setting `ALTER TABLE ... WRITE ORDERED BY customer_id` is the separate step
that makes *future* writes maintain it — and it is accepted by this lab if you want
to demonstrate it.

### 6. WRITE ORDERED BY, measured (added 2026-09-25)

Probed on a scratch table (`db.sortpolicy_probe`, created and dropped in place) so
the module's own `db.clustering` state was not disturbed.

| | snapshots | metadata versions | default sort-order |
|---|---|---|---|
| after first insert | 1 | 1 | 0 (unsorted) |
| after `ALTER TABLE ... WRITE ORDERED BY customer_id` | **1** | **2** | **1** |

So the ALTER writes a **new metadata version and no new snapshot**. That is the
precise shape of the claim: it is a policy change, not a data change. Nothing moves,
and the snapshot log does not grow.

**The next write does land sorted.** Inserted in the order `9, 4, 7`; read back from
the new data file in physical row order:

```
customer_id in physical row order: [4, 7, 9]
```

One quirk worth knowing: that new file still carries `sort_order_id=0` in its manifest
entry, not `1`. Spark applied the ordering to the rows but did not stamp the new
sort-order id on the file. So the file is sorted in fact while the metadata does not
advertise it — check the rows, not the id, if you are verifying this yourself.

This is the answer to the obvious question: if existing files never change, where can
you *see* the ordering? Only in files written after the policy. Existing files stay
exactly as they were until `rewrite_data_files` runs.

## Notes / gotchas

- **`write.distribution-mode = none` is load-bearing.** Spark's default shuffles rows
  before writing, which partially sorts each batch and makes the "scattered" layout
  look better than arrival order really is. With the default, the first probe measured
  8 of 24 files planned instead of 6 of 6 — a much weaker contrast that understates
  the problem.
- **`coalesce(1)` is why `02_load.py` uses the DataFrame API rather than
  `INSERT ... SELECT`.** Without it Spark splits each batch across several files and
  orders them on the way, again hiding the problem.
- **`rewrite-all` is required here.** These files are already near the target size, so
  the default cost-based check declines to rewrite and the procedure returns zeros —
  which looks like a failure and is not.
- **`target-file-size-bytes` must be small (8 KB) for this to be measurable.** At the
  512 MB default all 6,000 rows land in one file, and a single file can never skip
  anything. An early probe returned "1 of 1 files planned" and looked like broken
  pruning; the layout was simply too small to have anything to prune.
- **Do not use correlated columns to demonstrate z-order.** An early draft used
  `amt = id`, making the two columns perfectly correlated — z-order then looked like
  it was working when it was really just sorting one dimension. The independent-column
  version is what exposed the real behaviour.
- Field ids are read from `t.schema()` rather than hardcoded. Bounds are raw
  little-endian bytes (`<i` for int, `<d` for double); decoding with the wrong field id
  silently yields a plausible-looking wrong number.
- `plan_files()` can yield the same file more than once — de-duplicate by `file_path`
  before counting, or the file counts come out inflated.
- pyiceberg's snapshot `operation` is an **enum**; compare `op.value`, not the object.
- Spark SQL metadata tables (`db.clustering.files`) do **not** resolve against this
  REST catalog. Read metadata through pyiceberg, as every repro here does.

## Not demonstrated in this lab

- **Liquid clustering** is a Databricks Delta feature, not an Apache Iceberg one.
  There is nothing to run here, and no Iceberg equivalent to point at — Iceberg's
  answer to the same problem is sort orders plus periodic `rewrite_data_files`.
  Teach it as a comparison, not a procedure.
- **Partition skew** could not be shown honestly at this scale. Skew's cost is
  wall-clock: one task doing most of the work while the rest idle. With 6,000 rows
  every task finishes instantly, so a measured skew demo here would show a difference
  of milliseconds and prove nothing. The mechanism (a partition column whose values
  are wildly unbalanced) is worth teaching from the file-size and record-count columns
  this repro already prints, rather than from a fake timing.
