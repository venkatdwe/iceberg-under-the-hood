"""Module 01 exercise solutions — answers Q2 and Q3 from real metadata.

Run inside spark-iceberg:
    docker exec spark-iceberg python3 /tmp/05_solution.py q2
    docker exec spark-iceberg python3 /tmp/05_solution.py q3

Q2 — which manifest came from insert #1, and what proves it was reused rather
     than rewritten? (added_snapshot_id is the receipt.)
Q3 — filter for 2026-06-27: which manifest gets skipped at level 1, and which
     data file survives?
"""
import datetime
import sys

from pyiceberg.catalog.rest import RestCatalog
from pyiceberg.expressions import EqualTo

cat = RestCatalog(
    "demo",
    uri="http://rest:8181",
    warehouse="s3://warehouse/",
    **{"s3.endpoint": "http://minio:9000",
       "s3.access-key-id": "admin",
       "s3.secret-access-key": "password"},
)
tbl = cat.load_table("db.events")
io = tbl.io


def short(path):
    return path.split("/")[-1][:20] + "…"


def q2():
    """Every snapshot's manifest list, so reuse is visible side by side."""
    for s in sorted(tbl.metadata.snapshots, key=lambda x: x.sequence_number):
        print(f"snapshot {s.snapshot_id}  (sequence {s.sequence_number})")
        for m in s.manifests(io):
            print(f"    manifest {short(m.manifest_path)}"
                  f"   written_by_snapshot={m.added_snapshot_id}")
        print()
    print("The manifest whose added_snapshot_id is the FIRST snapshot appears")
    print("in BOTH lists — same path, same writer. Reused, not rewritten.")


def q3():
    """Level-1 prune for 2026-06-27, then the surviving data file."""
    days = (datetime.date(2026, 6, 27) - datetime.date(1970, 1, 1)).days
    want = days.to_bytes(4, "little")
    print(f"filter: event_date = 2026-06-27   ({days} days since epoch, "
          f"raw {want})\n")
    for m in tbl.current_snapshot().manifests(io):
        lo, hi = [(p.lower_bound, p.upper_bound) for p in (m.partitions or [])][0]
        verdict = "READ" if lo == hi == want else "SKIP  <- level-1 prune"
        print(f"  manifest {short(m.manifest_path)}  range=[{lo}, {hi}]  {verdict}")
    planned = list(tbl.scan(row_filter=EqualTo("event_date", days)).plan_files())
    print(f"\ndata files the planner kept = {len(planned)} of 2")
    for p in planned:
        print(f"  -> {p.file.file_path.split('/')[-1]}")


if __name__ == "__main__":
    {"q2": q2, "q3": q3}[sys.argv[1] if len(sys.argv) > 1 else "q2"]()
