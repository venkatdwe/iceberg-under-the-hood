"""Table-health inspector — the small-file metric, computed (not eyeballed).
Reusable across modules. Run: docker exec spark-iceberg python3 /tmp/health.py [db.table]
Reads pyiceberg metadata tables (works where Spark metadata-tables fail on the REST fixture)."""
import sys
from pyiceberg.catalog.rest import RestCatalog

TABLE = sys.argv[1] if len(sys.argv) > 1 else "db.events"
TARGET_MB = 128  # typical compaction target floor (128–512 MB)

cat = RestCatalog("demo", uri="http://rest:8181", warehouse="s3://warehouse/",
                  **{"s3.endpoint": "http://minio:9000",
                     "s3.access-key-id": "admin", "s3.secret-access-key": "password"})
t = cat.load_table(TABLE)

def mb(b): return b / 1_048_576

print(f"\n# Table health: {TABLE}")

# --- per-commit time series: avg file size as the table evolved ---
print("\n== avg file size per commit (snapshots.summary) — watch this TREND ==")
print(f"  {'committed_at':26}  {'total_files':>11}  {'total_bytes':>12}  {'avg_file_size':>14}")
snaps = t.inspect.snapshots().to_pylist()
for s in snaps:
    summ = dict(s["summary"])
    tf = int(summ.get("total-data-files", 0))
    tb = int(summ.get("total-files-size", 0))
    avg = tb / tf if tf else 0
    flag = "  <-- TINY" if tf and mb(avg) < 1 else ""
    print(f"  {str(s['committed_at']):26}  {tf:>11}  {tb:>12}  {mb(avg):>11.3f} MB{flag}")

# --- current state verdict ---
cur = snaps[-1]
summ = dict(cur["summary"])
tf = int(summ.get("total-data-files", 0)); tb = int(summ.get("total-files-size", 0))
avg_mb = mb(tb / tf) if tf else 0
print(f"\n== current: {tf} data files, {mb(tb):.3f} MB total, avg {avg_mb:.3f} MB/file ==")
verdict = "HEALTHY" if avg_mb >= TARGET_MB else f"SMALL-FILE RISK (avg {avg_mb:.3f} MB << {TARGET_MB} MB target)"
print(f"   verdict vs {TARGET_MB} MB target: {verdict}")

# --- where: per-partition concentration ---
# An UNPARTITIONED table has no `partition` column in its partitions metadata
# table -- pyiceberg returns a single row describing the whole table instead.
# Module 05's db.trickle is unpartitioned on purpose, and it is the table most
# worth running this on, so this must not assume the column exists.
parts = t.inspect.partitions().to_pylist()
partitioned = bool(parts) and "partition" in parts[0]
if partitioned:
    print("\n== per-partition file_count + avg size (partitions) — WHERE to compact ==")
    print(f"  {'partition':28}  {'files':>5}  {'total_bytes':>12}  {'avg_file_size':>14}")
else:
    print("\n== whole-table file_count + avg size — this table is UNPARTITIONED ==")
    print(f"  {'scope':28}  {'files':>5}  {'total_bytes':>12}  {'avg_file_size':>14}")
for p in parts:
    fc = p["file_count"]; sz = p["total_data_file_size_in_bytes"]
    avg = sz / fc if fc else 0
    label = str(p["partition"]) if partitioned else "(unpartitioned)"
    print(f"  {label:28}  {fc:>5}  {sz:>12}  {mb(avg):>11.3f} MB")
