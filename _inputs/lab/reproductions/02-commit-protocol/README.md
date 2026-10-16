# Repro #2 — The Commit Protocol: Compare-and-Swap & Optimistic Concurrency

**Goal:** watch a commit atomically move the catalog pointer, then watch two writers race and
see the loser get rejected by compare-and-swap and retry. The concrete version of Module 02.

## Stack
docker-spark-iceberg (catalog `demo` → MinIO). Reuses the `db.events` table from repro #1.

## Steps
```bash
# reset to the clean 4-row baseline (from repro #1)
docker exec spark-iceberg spark-sql -f /tmp/01_create.sql
# run the commit + concurrency demo
docker cp 01_commit.py spark-iceberg:/tmp/ && docker exec spark-iceberg python3 /tmp/02_commit.py
```

## Measured output (these become the module hooks)

**Part 1 — a commit moves the pointer:**
```
BEFORE: current_snapshot=6611747986655168499  parent=2076853821677781488  prior metadata.json=2
AFTER : current_snapshot=2254263999421742136  parent=6611747986655168499  prior metadata.json=3
  -> new snapshot's parent == old current : True
  -> a NEW metadata.json was written (2 -> 3)
```
A commit = write new immutable metadata, then **swap the catalog's single pointer** to it.
The new snapshot's `parent` is exactly the snapshot that was current — that's the linearized history.

**Part 2 — two writers race (optimistic concurrency):**
```
both writers start from base snapshot = 2254263999421742136
writer 1 commits first -> 2433854024263663067 (parent 2254...)
writer 2 REJECTED: CommitFailedException: Requirement failed:
         branch main has changed: expected id 2254263999421742136 != 2433854024263663067
writer 2 RETRIES on fresh metadata -> 3037591172074573880 (parent 2433854024263663067)
  -> re-parented on the winner : True   (no lock; the loser simply retried)
final snapshot chain length = 5;  final row count = 7
```

## The takeaways
- **No lock.** Concurrency is **optimistic**: each commit asserts "the branch is still at the
  snapshot I started from." That assertion *is* the compare-and-swap.
- **The loser doesn't fail — it retries.** Re-read current metadata, re-apply the change, swap again.
  Its new snapshot re-parents on the winner, so history stays a clean linear chain.
- **Atomicity is the single pointer swap.** A reader resolves the catalog pointer to *one*
  metadata.json — the old one or the new one, never a half-written state.

## The hook (for Module 02)
"Two writers committed at the same instant. There was no lock. One won; the other was told
'the table moved under you' — `expected 2254… != 2433…` — and simply retried. That rejection
message *is* Iceberg's entire concurrency model."

> Note: this repro mutates `db.events` to 7 rows / 5 snapshots. Re-run repro #1's `01_create.sql`
> to return to the clean baseline.
