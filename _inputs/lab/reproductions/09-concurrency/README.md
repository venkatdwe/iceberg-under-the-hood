# Repro #9 — "branch main has changed": losing a race and getting back from a mistake

**Goal:** show the commit protocol doing its job, in both directions. Two writers
start from the same snapshot and one is refused; then a wrong `DELETE` destroys a
hundred rows and is undone without a backup. Both are the same mechanism — a
pointer with an assertion on it — seen from opposite sides. The concrete version
of Module 09.

## Stack
docker-spark-iceberg (catalog `demo`, Spark 3.5.6, Iceberg 1.9.0, pyiceberg 0.9.1).
One table, `db.concurrent`, deliberately tiny: the subject is the commit protocol,
and a large table would only add noise to the snapshot chain the module reads on
screen. Three separate inserts, so there is a real history to travel across.

## Run
```bash
just m09-concurrent
# or manually:
docker exec spark-iceberg spark-sql -f /tmp/09_setup.sql
docker exec spark-iceberg python3   /tmp/09_conflict.py     # layers 1-4
docker exec spark-iceberg python3   /tmp/09_recover.py      # layers 5-8
docker exec spark-iceberg python3   /tmp/09_timetravel.py   # layers 9-10
```

`03_recover.py` must run against a freshly set-up table — it captures "the good
state" as whatever it finds on entry, so running it twice makes the second run
roll back to the already-broken state.

## Measured result (these become the module hooks)

**Snapshot ids regenerate on every run. The counts and the error do not.**

### The headline: the rejection is an assertion, not a lock

```
writer A starts from snapshot   6988249085177089379
writer B starts from snapshot   6988249085177089379
same base: True

writer A commits    -> table now at 3886390179789781957
writer B commits    -> REJECTED: CommitFailedException
   Requirement failed: branch main has changed: expected id 6988249085177089...
```

**Nothing was wrong with B's data.** B was refused because the base it promised to
build on had moved. That is the whole of Iceberg's concurrency control: no writer
takes a lock, each states the snapshot it started from, and the catalog swaps the
pointer only if the table is still sitting on it.

The error message is the best teaching artifact in this repro — `branch main has
changed: expected id ...` says the mechanism out loud.

### The retry costs one round trip

```
writer B re-reads the table:  3886390179789781957
writer B commits              -> 3186646855629289257

rows now in the table: 340
  ap-south  20   eu-west  100   sa-east  20   us-east  100   us-west  100
```

Both writes survive. Nothing was lost and nothing was silently overwritten,
because two appends do not conflict on *content* — only on the pointer. That is
why an append can be retried automatically and a merge often cannot.

### A bad DELETE is a pointer problem

```
before:  340 rows, 5 snapshots
DELETE FROM db.concurrent WHERE region = 'us-east'
after:   240 rows, 6 snapshots     (100 rows "destroyed")
```

Nothing is actually destroyed at this point. The files those rows live in are
still on disk and still referenced by the previous snapshot.

### Rollback, and the thing everyone gets wrong about it

```
CALL demo.system.rollback_to_snapshot(table => 'db.concurrent', snapshot_id => ...)

rows                 340   (was 240)
snapshots in history   6   (was 6)
```

**The snapshot count does not change.** Rollback does not add a snapshot and does
not erase one — the branch ref simply points somewhere else. So the bad commit
stays in the list, auditable, and rolling *forward* to it again is the same
operation. Recovery took no restore, no backup and no re-ingest.

### Time travel is the same list read from the other end

```
snapshot              operation     rows readable AS OF that snapshot
2394606476975865434   append          100
2377705011885710786   append          200
6956665634564088949   append          300
7108328396574118728   append          320
 971914278475161385   append          340   <- current
2870114609996139832   delete          240
```

Every snapshot the chain still holds is a complete, queryable table — which is
exactly why the rollback needed nothing but a pointer. And the horizon is
retention: the table is queryable at six points in time and no others. Expiring
snapshots (Module 06) is what deletes the past, and it is the same operation you
run to stop paying for it. **Recovery window and storage bill are one dial.**

## Notes / gotchas

- **pyiceberg 0.9.1 cannot roll back.** `ManageSnapshots` exposes only
  `create_branch`, `create_tag`, `remove_branch`, `remove_tag` — there is no
  `rollback_to_snapshot`, and calling it raises `AttributeError`. Use the Spark
  procedure, which is what an operator reaches for anyway.
- **The conflict is deterministic, and deliberately so.** Both writers load the
  table independently and therefore hold the same base; A commits, B is refused.
  Racing two real processes would demonstrate the identical rule while making the
  recording depend on thread scheduling.
- **`t.refresh()` after a commit**, or `current_snapshot_id` still reports the
  pre-commit value and the layer prints a number that looks like a failed write.
- **Re-running `03_recover.py` without re-running setup** captures the broken
  state as "good" and rolls back into it. The demo silently inverts.
- pyiceberg's snapshot `operation` is an **enum**; compare `op.value`.
- Spark SQL metadata tables do **not** resolve against this REST catalog; read
  metadata through pyiceberg.

## Not demonstrated in this lab

- **A true write-write conflict on the same rows.** Two appends conflict only on
  the pointer, which is why B's retry is trivially safe. A `MERGE` or a
  `DELETE` racing another writer's rewrite of the same files can fail validation
  *again* after refreshing, and no amount of retrying fixes it. Showing that
  needs a second engine writing concurrently; it is worth teaching as the reason
  "just retry" is not a universal answer, rather than faking a demo of it.
- **Autonomous / managed optimization.** Table-maintenance services (Snowflake's
  automatic clustering, Databricks predictive optimization, Tabular-style managed
  compaction) have nothing to run against here — there is no vendor service in
  this lab. Teach it as what these repros already measure being run by someone
  else on a schedule, not as a feature demo.
- **Recovery from a corrupted or deleted metadata file.** That path needs
  `register_table` against object storage and a broken warehouse to point it at;
  breaking the lab's MinIO to film it would cost every other module's tables.
