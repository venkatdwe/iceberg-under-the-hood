# Repro #14 — one table, every engine, and the moment they disagree

**Goal:** the capstone. Modules 01–13 established that data files are portable,
that the catalog is an HTTP contract, and that a rollback moves a branch ref.
This puts all three together and finds the seam — a table where two engines
return different answers and neither one errors.

## Stack
docker-spark-iceberg (Spark 3.5.6, Iceberg 1.9.0, pyiceberg 0.9.1) plus **DuckDB
1.5.2** on the host. One table, `db.interop`, created and destroyed entirely
within this module.

Three engines, three code bases, one catalog: Spark writes, pyiceberg reads from
inside the container, DuckDB reads from the host over `localhost:8181`.

## Run
```bash
just m14-interop
# or manually:
docker exec spark-iceberg spark-sql -f /tmp/14_setup.sql
docker exec spark-iceberg python3   /tmp/14_break.py     # layers 1-4
duckdb -c ".read 03_duckdb.sql"                          # from the HOST
```

`02_break_and_recover.py` must run against a freshly set-up table — it captures
"the good snapshot" as whatever it finds on entry, so a second run without
re-running setup rolls back into the already-broken state.

## Measured result

**Snapshot ids regenerate on every run. The row counts and the disagreement do
not.**

### Setup: 300 rows, three engines, no argument

A plain table, three appends, nothing unusual. Every reader agrees.

### Then a wrong predicate, and module 09's recovery

```
DELETE FROM db.interop WHERE region = 'us-east'
  rows  200   (was 300)

CALL demo.system.rollback_to_snapshot(table => 'db.interop', snapshot_id => ...)
  rows                300   (recovered)
  snapshots retained    4   (was 4 before the rollback — unchanged; only the ref moved)
```

Exactly module 09's result: the mistake is still on the record, nothing was
erased, and the branch ref moved back.

### The catalog is now split, and that is normal

```
  seq  operation   snapshot
    1  append      8483208842304475196
    2  append      8621352866083134799
    3  append      6455280268197102896   <- main
    4  delete      1382281656596201835   <- newest
```

`main` and "the newest snapshot" are **different snapshots**. That is what every
rollback leaves behind. It is not a broken state — it is the correct one.

### The headline: two engines, two answers, no error

| reader | rows | which snapshot it followed |
|---|---|---|
| pyiceberg 0.9.1 | **300** | `main` — sees the recovery |
| DuckDB 1.5.2, default scan | **200** | the newest — misses it |
| DuckDB 1.5.2, `AT (VERSION => <main>)` | **300** | pinned explicitly |

The recovery completed. Spark and pyiceberg agree it completed. And a third
engine, reading the same catalog a second later, still returns the broken state
— **without raising anything**.

That is the failure mode worth the whole module: not a crash, not corruption,
just two correct-looking answers to the same question.

### And the fix

DuckDB's attached-catalog tables accept an explicit snapshot:

```sql
SELECT count(*) FROM ice.db.interop AT (VERSION => <main snapshot id>);
-- 300
```

So the instruction is concrete. After any rollback: check what each reader
resolves, and pin the snapshot wherever the engine lets you. This is not
"DuckDB is broken" — it is that `main` and `newest` diverge by design, and
engines differ in which one they follow.

## Notes / gotchas

- **Spark SQL metadata tables do not resolve against this REST catalog.** The
  rollback step was first written as SQL with a `db.interop.snapshots` subquery
  and failed. Read the snapshot through pyiceberg and hand it to the Spark
  procedure — the same shape module 09 uses. This course has now hit this in
  three modules.
- **`iceberg_scan()` against a raw `s3://` path is a different access mode** and
  refuses without a version hint (`unsafe_enable_version_guessing`). The pinning
  above works through the ATTACHed catalog, which is the path this course uses.
- **`AUTHORIZATION_TYPE 'none'`** is required on the DuckDB attach; without it
  DuckDB assumes oauth2 and fails with "no 'secret' was provided".
- **Never hardcode the snapshot id.** It regenerates every run; the capture
  script substitutes it from the catalog's own `main` ref.
- **Re-running step 2 without re-running setup** captures the broken state as
  "good" and inverts the demo.

## Not demonstrated in this lab

- **Whether other engines follow `main` or `newest`.** Only pyiceberg and DuckDB
  were tested. Trino, Flink and the vendor engines are the obvious next
  candidates, and the module should present two data points as two data points —
  not as a rule about "Python clients" or "analytical engines".
- **Whether this is fixed in a later DuckDB.** The measurement is 1.5.2. The
  module must say the version out loud, because the lesson is "verify your own
  stack", not "this engine is wrong".
- **Concurrent writes from two engines.** Every write here comes from Spark.
  Genuine bidirectional write interop needs a second writing engine, which this
  lab does not have — teach it as the harder problem it is rather than implying
  the read-side result covers it.
