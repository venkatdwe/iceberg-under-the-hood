"""Lab repro #2 — watch a commit move the catalog pointer, and watch two writers race.
Run: docker exec spark-iceberg python3 /tmp/02_commit.py
Demonstrates: atomic pointer swap (compare-and-swap) + optimistic concurrency + retry."""
import datetime
import pyarrow as pa
from pyiceberg.catalog.rest import RestCatalog
from pyiceberg.exceptions import CommitFailedException

cat = RestCatalog("demo", uri="http://rest:8181", warehouse="s3://warehouse/",
                  **{"s3.endpoint": "http://minio:9000",
                     "s3.access-key-id": "admin", "s3.secret-access-key": "password"})

def row(i, d, u, a):
    return pa.table({"id": pa.array([i], pa.int64()),
                     "event_date": pa.array([datetime.date.fromisoformat(d)], pa.date32()),
                     "user": pa.array([u], pa.string()),
                     "amt": pa.array([a], pa.float64())})

def cur(t):
    s = t.current_snapshot()
    return (s.snapshot_id, s.parent_snapshot_id)

print("\n========== PART 1: a commit moves the pointer (compare-and-swap) ==========")
t = cat.load_table("db.events")
before_id, before_parent = cur(t)
before_meta = len(t.metadata.metadata_log)   # number of PRIOR metadata.json files
print(f"BEFORE:  current_snapshot={before_id}  parent={before_parent}  prior metadata.json count={before_meta}")

t.append(row(5, "2026-06-29", "dave", 50.0))

t = cat.load_table("db.events")
after_id, after_parent = cur(t)
after_meta = len(t.metadata.metadata_log)
print(f"AFTER :  current_snapshot={after_id}  parent={after_parent}  prior metadata.json count={after_meta}")
print(f"  -> pointer moved {before_id} -> {after_id};  new snapshot's parent == old current? {after_parent == before_id}")
print(f"  -> a NEW metadata.json was written (count {before_meta} -> {after_meta})")

print("\n========== PART 2: two writers race (optimistic concurrency + retry) ==========")
base = cat.load_table("db.events")
base_id = base.current_snapshot().snapshot_id
print(f"both writers start from base snapshot = {base_id}")

w1 = cat.load_table("db.events")   # writer 1, base
w2 = cat.load_table("db.events")   # writer 2, SAME base (the 'stale' one)

w1.append(row(6, "2026-06-29", "erin", 60.0))
w1r = cat.load_table("db.events")
win = w1r.current_snapshot().snapshot_id
print(f"writer 1 commits first -> snapshot {win} (parent {w1r.current_snapshot().parent_snapshot_id})")

# writer 2 started from the now-stale base. Append anyway -> compare-and-swap should REJECT it:
try:
    w2.append(row(7, "2026-06-29", "frank", 70.0))
    print("writer 2 committed without conflict (unexpected for this demo)")
except CommitFailedException as e:
    print("writer 2 commit REJECTED by compare-and-swap:")
    print(f"    {str(e).splitlines()[0]}")
    print(f"  -> it asserted base {base_id} was still current; the catalog had already moved to {win}")
    # THE RETRY: reload fresh metadata, re-apply the same change
    w2_retry = cat.load_table("db.events")
    w2_retry.append(row(7, "2026-06-29", "frank", 70.0))
    w2rr = cat.load_table("db.events")
    rid, rparent = cur(w2rr)
    print(f"writer 2 RETRIES on fresh metadata -> snapshot {rid} (parent {rparent})")
    print(f"  -> now parented on the winner? {rparent == win}   (no lock; the loser simply retried)")

final = cat.load_table("db.events")
print(f"\nfinal snapshot chain length = {len(final.metadata.snapshots)};  final row count = {final.scan().to_arrow().num_rows}")
