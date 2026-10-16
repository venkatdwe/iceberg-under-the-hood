"""Repro #9, step 4 — reading the past, and what makes it stop being readable.

Run: docker exec spark-iceberg python3 /tmp/09_timetravel.py   (AFTER 03_recover.py)

Time travel is not a feature bolted onto the table; it is the snapshot list read
from the other end. Every snapshot the chain still holds is a complete, queryable
table, which is why the rollback in step 3 needed no backup.

The last layer is the one worth teaching honestly: time travel has a horizon,
and the horizon is retention. Module 06's expiry is what removes it.
"""
from pyiceberg.catalog.rest import RestCatalog

cat = RestCatalog(
    "demo", uri="http://rest:8181", warehouse="s3://warehouse/",
    **{"s3.endpoint": "http://minio:9000",
       "s3.access-key-id": "admin", "s3.secret-access-key": "password"},
)
t = cat.load_table("db.concurrent")

print("\n========== LAYER 9: EVERY SNAPSHOT IS A READABLE TABLE ==========")
print("  snapshot              operation     rows readable AS OF that snapshot")
for s in t.metadata.snapshots:
    op = getattr((s.summary or {}).get("operation"), "value", "?")
    try:
        n = t.scan(snapshot_id=s.snapshot_id).to_arrow().num_rows
        n = f"{n:>5}"
    except Exception:
        n = "    ?"
    marker = "  <- current" if s.snapshot_id == t.metadata.current_snapshot_id else ""
    print(f"  {s.snapshot_id}  {op:<12}  {n}{marker}")

print("  -> no restore, no snapshot-of-a-snapshot, no separate history table.")
print("     Reading the past is the same scan against a different pointer.")

print("\n========== LAYER 10: THE HORIZON ==========")
n = len(t.metadata.snapshots)
print(f"  snapshots retained right now: {n}")
print(f"  so the table is queryable at {n} points in time, and no others.")
print("  -> time travel does not reach further back than retention allows.")
print("     Expiring snapshots (Module 06) is what deletes the past, and it is")
print("     the same operation you run to stop paying for it. Recovery window")
print("     and storage bill are the same dial — you cannot tune one alone.")
