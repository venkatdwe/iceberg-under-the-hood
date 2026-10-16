"""Repro #9, step 3 — a bad commit, and getting back from it without a restore.

Run: docker exec spark-iceberg python3 /tmp/09_recover.py   (AFTER 02_conflict.py)

The point of the snapshot chain is that a mistake is a pointer problem, not a
data-loss problem. A wrong DELETE does not destroy anything — it writes a new
snapshot that omits some rows. The previous snapshot is still there, still
complete, and rolling back is another pointer swap.

Note what rollback does NOT do: it does not truncate history. Measured here the
snapshot count is identical before and after — the bad commit is still listed,
and only the branch ref moved. So the mistake stays auditable and rolling
forward to it is the same operation. That is the opposite of what "rollback"
suggests to most people, and it is the useful half of the behaviour.
"""
import subprocess

from pyiceberg.catalog.rest import RestCatalog

cat = RestCatalog(
    "demo", uri="http://rest:8181", warehouse="s3://warehouse/",
    **{"s3.endpoint": "http://minio:9000",
       "s3.access-key-id": "admin", "s3.secret-access-key": "password"},
)


def load():
    return cat.load_table("db.concurrent")


def count(t) -> int:
    return t.scan().to_arrow().num_rows


def history(t) -> list:
    return list(t.metadata.snapshots)


t = load()
good_snapshot = t.metadata.current_snapshot_id
good_rows = count(t)

print("\n========== LAYER 5: THE STATE WE ARE ABOUT TO RUIN ==========")
print(f"  current snapshot   {good_snapshot}")
print(f"  rows               {good_rows}")
print(f"  snapshots in history {len(history(t))}")

# ── the mistake ───────────────────────────────────────────────────────────
# A filter that was meant to remove one region and removed it from every row
# that had ever been written. The most ordinary production incident there is.
print("\n========== LAYER 6: A BAD COMMIT ==========")
t.delete(delete_filter="region = 'us-east'")
t = load()
bad_snapshot = t.metadata.current_snapshot_id
bad_rows = count(t)
print(f"  after the delete:  {bad_rows} rows  (was {good_rows})")
print(f"  rows destroyed:    {good_rows - bad_rows}")
print(f"  current snapshot   {bad_snapshot}")
print(f"  snapshots in history {len(history(t))}")
print("  -> nothing has actually been destroyed yet. The data files those rows")
print("     lived in are still on disk, still referenced by the previous")
print("     snapshot. Only the pointer moved.")

# ── the recovery ──────────────────────────────────────────────────────────
print("\n========== LAYER 7: ROLLBACK ==========")
# Rollback goes through the Spark procedure rather than pyiceberg: 0.9.1's
# ManageSnapshots only manages branches and tags, and this is the call an
# operator actually reaches for at 3am anyway.
call = (f"CALL demo.system.rollback_to_snapshot("
        f"table => 'db.concurrent', snapshot_id => {good_snapshot}L)")
print(f"  {call}")
subprocess.run(["spark-sql", "-e", call],
               capture_output=True, text=True, check=True)
t = load()
print(f"  rolled back to     {good_snapshot}")
print(f"  rows              {count(t)}  (was {bad_rows} a moment ago)")
print(f"  snapshots in history {len(history(t))}")
print("  -> recovery took no restore, no backup and no re-ingest. It took one")
print("     pointer swap, because the old snapshot never stopped being valid.")

# ── what rollback did to the record ───────────────────────────────────────
print("\n========== LAYER 8: HISTORY IS APPEND-ONLY ==========")
print("  the bad commit is STILL in the snapshot list:")
for s in history(t):
    op = getattr((s.summary or {}).get("operation"), "value", "?")
    mark = ""
    if s.snapshot_id == bad_snapshot:
        mark = "   <- the mistake, still on the record"
    elif s.snapshot_id == good_snapshot:
        mark = "   <- rolled back to here"
    print(f"    {s.snapshot_id}  {op:<10}{mark}")
print("  -> rollback did not erase the mistake, and did not add a snapshot")
print("     either — the count is unchanged. All that moved was the ref. The")
print("     bad commit stays auditable, and rolling forward to it again is the")
print("     same operation. Snapshots leave for one reason only: expiry (06).")
