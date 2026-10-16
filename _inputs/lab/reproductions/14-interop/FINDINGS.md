# Module 14 findings — measured 2026-09-03, needs one confirmation pass

Probe run while building module 09. Recorded here because it is the strongest
capstone material found so far, and because it would be lost otherwise.

## Interop is real in this lab — no vendor account needed

Module 14 was scoped as slide-only on the assumption that "one table, every
engine" needs Snowflake or Databricks. It does not. Measured:

- MinIO is published on `localhost:9000`, the REST catalog on `localhost:8181`.
- DuckDB **v1.5.2** is installed on the host and its `iceberg` extension can
  `ATTACH` the lab's catalog directly.

```sql
INSTALL iceberg; LOAD iceberg;
CREATE SECRET (TYPE s3, KEY_ID 'admin', SECRET 'password',
               ENDPOINT 'localhost:9000', USE_SSL false, URL_STYLE 'path');
ATTACH 'warehouse' AS ice (TYPE iceberg,
       ENDPOINT 'http://localhost:8181', AUTHORIZATION_TYPE 'none');
```

`AUTHORIZATION_TYPE 'none'` is required — without it DuckDB assumes oauth2 and
fails with "no 'secret' was provided". That one parameter is the whole barrier.

DuckDB then lists and reads every table Spark wrote: `db.clustering`,
`db.concurrent`, `db.gov_cow`, `db.gov_mor`. Three engines (Spark, pyiceberg,
DuckDB) against one table, no vendor involved. **Module 14 can be a real
capstone rather than a slide deck.**

## The headline: after a rollback, the engines disagree

Module 09's repro leaves `db.concurrent` rolled back to the good snapshot.

| reader | rows returned |
|---|---|
| pyiceberg (`t.scan()`) | **340** |
| DuckDB 1.5.2 `SELECT count(*)` | **240** |

240 is the state the rollback *undid*. The catalog is unambiguous about which
is current:

```
current-snapshot-id : 971914278475161385
refs                : {'main': 971914278475161385}

            snapshot              ms  seq  op        is_main
 2394606476975865434   1788418647805    1  append    False
 2377705011885710786   1788418657497    2  append    False
 6956665634564088949   1788418664065    3  append    False
 7108328396574118728   1788418712651    4  append    False
  971914278475161385   1788418716174    5  append    True     <- 340 rows
 2870114609996139832   1788418741918    6  delete    False    <- 240 rows
```

`main` points at sequence 5. The newest snapshot by both timestamp and sequence
number is 6 — the bad `DELETE`. DuckDB returned 240 rows, so **it resolved the
latest snapshot rather than the branch ref the catalog calls `main`.**

Rollback moves a ref (module 09 measures this: 6 snapshots before, 6 after,
nothing erased). An engine that reads "newest snapshot" instead of "the ref"
therefore does not see the rollback at all. The recovery looks complete from
Spark and pyiceberg and has silently not happened for the third engine.

This is the best argument the course has for why the spec's distinction between
snapshots and refs matters in practice, and it is exactly the channel's line —
everyone explains the API, we open the files.

### Reproduced a second time

While building repro #11, DuckDB read `db.concurrent` again from a fresh process
and returned the same 240. Independent of the first probe, same result — this is
stable behaviour, not a one-off. In the same session DuckDB read `db.gov_cow`
(no rollback in its history) and returned 4,999, exactly matching Spark. So the
divergence is specific to the rollback, not a general disagreement about the
warehouse.

## CONFIRMED 2026-09-08 — on a clean, purpose-built table

`db.interop` is created, written, broken and recovered entirely within this
module (`01_setup.sql`, `02_break_and_recover.py`). After the rollback:

```
  seq  operation   snapshot
    1  append      8483208842304475196
    2  append      8621352866083134799
    3  append      6455280268197102896   <- main
    4  delete      1382281656596201835   <- newest
```

| reader | rows | which snapshot it followed |
|---|---|---|
| pyiceberg | **300** | `main` — the recovery |
| DuckDB 1.5.2, default scan | **200** | the newest snapshot — the mistake |
| DuckDB 1.5.2, `AT (VERSION => <main>)` | **300** | pinned explicitly |

So the hazard reproduces exactly on a table built for it, and **there is a
fix**: DuckDB's attached-catalog tables accept `AT (VERSION => <snapshot_id>)`
and then return the correct state.

That matters for how the module teaches it. This is not "DuckDB is broken" — it
is that a rollback leaves `main` and `newest` pointing at different snapshots,
and an engine which resolves the newest silently misses the recovery. The
instruction is: after any rollback, verify what each reader resolves, and pin
the snapshot where the engine lets you.

Note `iceberg_scan()` against a raw `s3://` path is a different access mode and
refuses without a version hint (`unsafe_enable_version_guessing`). The pinning
above works through the ATTACHed catalog, which is the path this course uses.

## Before this ships
2. **Check whether DuckDB exposes a snapshot/ref selector** (`iceberg_scan`
   options, `snapshot_from_id`). If it can be pointed at `main` explicitly, the
   module teaches the fix as well as the hazard — much better than teaching
   only the trap.
3. **Pin the version in the narration.** This is DuckDB 1.5.2 behaviour and may
   change. The module should say the version out loud and frame the lesson as
   "verify which snapshot your engine resolves", not "DuckDB is broken".
4. Check the same question for pyiceberg's own `snapshot_id=` scans and for
   Spark's `VERSION AS OF`, so the module compares three engines rather than
   accusing one.

## Related: missing tables

`db.lifecycle`, `db.trickle`, `db.evolve` and `db.events` are no longer in the
catalog. Modules 06 and 07 already have their `captured_output.json`, so nothing
shipped is at risk, but a re-capture of module 06 would need its repro re-run
first rather than assuming the lab still holds those tables.
