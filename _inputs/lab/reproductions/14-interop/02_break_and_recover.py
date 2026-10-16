"""Repro #14, step 2 — a bad delete, then module 09's rollback.

Run: docker exec spark-iceberg python3 /tmp/14_break.py

Deliberately the same shape as module 09 so the viewer recognises it: one wrong
predicate removes a third of the table, and rollback moves the branch ref back
without erasing anything.

What module 09 could not show is what the OTHER engines think happened. Step 3
measures that, and it is the whole point of this module.

Python rather than SQL because Spark SQL metadata tables (`table.snapshots`) do
NOT resolve against this REST catalog — a gotcha this course has now hit in
three modules. The snapshot id is read through pyiceberg and handed to the Spark
procedure, exactly as module 09's recovery script does.
"""
import datetime as _dt
import subprocess

from pyiceberg.catalog.rest import RestCatalog

cat = RestCatalog(
    "demo", uri="http://rest:8181", warehouse="s3://warehouse/",
    **{"s3.endpoint": "http://minio:9000",
       "s3.access-key-id": "admin", "s3.secret-access-key": "password"},
)


def load():
    return cat.load_table("db.interop")


t = load()
good = t.metadata.current_snapshot_id
before = t.scan().to_arrow().num_rows

print("\n========== LAYER 1: THE STATE EVERY ENGINE AGREES ON ==========")
print(f"  rows                {before}")
print(f"  current snapshot    {good}")
print(f"  snapshots retained  {len(t.metadata.snapshots)}")

# ── the mistake ───────────────────────────────────────────────────────────
print("\n========== LAYER 2: A BAD DELETE ==========")
t.delete(delete_filter="region = 'us-east'")
t = load()
bad = t.metadata.current_snapshot_id
print(f"  DELETE FROM db.interop WHERE region = 'us-east'")
print(f"  rows                {t.scan().to_arrow().num_rows}   (was {before})")
print(f"  current snapshot    {bad}")

# ── and module 09's recovery ─────────────────────────────────────────────
n_before_rollback = len(t.metadata.snapshots)
print("\n========== LAYER 3: ROLLBACK ==========")
call = (f"CALL demo.system.rollback_to_snapshot("
        f"table => 'db.interop', snapshot_id => {good}L)")
print(f"  {call}")
subprocess.run(["spark-sql", "-e", call], capture_output=True, text=True, check=True)
t = load()
print(f"  rows                {t.scan().to_arrow().num_rows}   (recovered)")
print(f"  snapshots retained  {len(t.metadata.snapshots)}   "
      f"(was {n_before_rollback} before the rollback — unchanged; only the ref moved)")

# ── what the catalog now says is current ─────────────────────────────────
print("\n========== LAYER 4: WHAT THE CATALOG SAYS ==========")
refs = {k: v.snapshot_id for k, v in (t.metadata.refs or {}).items()}
newest = max(t.metadata.snapshots, key=lambda s: (s.sequence_number, s.timestamp_ms))
print(f"  refs                {refs}")
print(f"  newest snapshot     {newest.snapshot_id}  (sequence {newest.sequence_number})")
print(f"  main points at      {refs.get('main')}")
print()
# Timestamps included deliberately: "newest" is a claim about time, and the
# viewer should be able to see that the ref does NOT point at the latest one.
print("  seq  operation   committed             snapshot              is main?")
for s in t.metadata.snapshots:
    op = getattr((s.summary or {}).get("operation"), "value", "?")
    mark = "  <- main" if s.snapshot_id == refs.get("main") else ""
    newest_mark = "  <- newest" if s.snapshot_id == newest.snapshot_id else ""
    ts = _dt.datetime.fromtimestamp(s.timestamp_ms / 1000).strftime("%H:%M:%S")
    print(f"  {s.sequence_number:>3}  {op:<10}  {ts}              {s.snapshot_id}{mark}{newest_mark}")
print()
print("  -> main and 'newest' are now DIFFERENT snapshots. That is what a")
print("     rollback leaves behind, and it is where engines can part company:")
print("     one that follows the ref sees the recovery, one that follows the")
print("     newest snapshot does not.")
