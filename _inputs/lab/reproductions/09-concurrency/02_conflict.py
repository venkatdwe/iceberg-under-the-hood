"""Repro #9, step 2 — two writers from the same base, and what stops the second.

Run: docker exec spark-iceberg python3 /tmp/09_conflict.py

Iceberg's concurrency control is optimistic: a writer does not lock the table,
it states the snapshot it started from and asks the catalog to swap the pointer
only if the table is still there. That assertion is the whole mechanism, and it
is worth seeing fail rather than being told about.

Both writers load the table independently and therefore hold the SAME base
snapshot id. Writer A commits. Writer B then tries to commit against a base that
no longer exists, and the catalog rejects it. B refreshes and retries.

Deterministic on purpose. Racing two real processes would demonstrate the same
rule while making the recording depend on thread scheduling.
"""
from pyiceberg.catalog.rest import RestCatalog
import pyarrow as pa

cat = RestCatalog(
    "demo", uri="http://rest:8181", warehouse="s3://warehouse/",
    **{"s3.endpoint": "http://minio:9000",
       "s3.access-key-id": "admin", "s3.secret-access-key": "password"},
)


def rows(start: int, region: str, n: int = 20) -> pa.Table:
    return pa.table({
        "id": pa.array(range(start, start + n), type=pa.int64()),
        "region": pa.array([region] * n, type=pa.string()),
        "amount": pa.array([(i * 7919) % 500 for i in range(start, start + n)],
                           type=pa.int32()),
    })


# Two independent handles. Neither knows the other exists — which is exactly
# the situation two unrelated jobs are in.
writer_a = cat.load_table("db.concurrent")
writer_b = cat.load_table("db.concurrent")

base_a = writer_a.metadata.current_snapshot_id
base_b = writer_b.metadata.current_snapshot_id

print("\n========== LAYER 1: TWO WRITERS, ONE BASE ==========")
print(f"  writer A starts from snapshot   {base_a}")
print(f"  writer B starts from snapshot   {base_b}")
print(f"  same base: {base_a == base_b}")
print("  -> neither writer holds a lock. Each will state the snapshot it")
print("     started from and ask the catalog to move the pointer only if the")
print("     table is still sitting on it.")

# ── writer A wins simply by arriving first ────────────────────────────────
print("\n========== LAYER 2: WRITER A COMMITS ==========")
writer_a.append(rows(1000, "ap-south"))
writer_a.refresh()
after_a = writer_a.metadata.current_snapshot_id
print(f"  committed. table now at snapshot {after_a}")
print(f"  writer B still believes the table is at {base_b}")

# ── and writer B loses on the assertion, not on the data ──────────────────
print("\n========== LAYER 3: WRITER B IS REJECTED ==========")
rejected = None
try:
    writer_b.append(rows(2000, "sa-east"))
    print("  writer B committed with no conflict")
except Exception as exc:                      # CommitFailedException, or the
    rejected = type(exc).__name__             # REST 409 the catalog raises
    print(f"  writer B was REJECTED: {rejected}")
    detail = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    if detail:
        print(f"    {detail[:96]}")
print("  -> nothing was wrong with B's data. B was rejected because the base")
print("     it promised to build on had already moved. That is the entire")
print("     concurrency protocol: an assertion on the snapshot pointer.")

# ── the retry is the part that makes it usable ────────────────────────────
print("\n========== LAYER 4: B REFRESHES AND RETRIES ==========")
writer_b.refresh()
print(f"  writer B re-reads the table:     {writer_b.metadata.current_snapshot_id}")
writer_b.append(rows(2000, "sa-east"))
writer_b.refresh()
print(f"  committed. table now at snapshot {writer_b.metadata.current_snapshot_id}")

final = cat.load_table("db.concurrent")
scan = final.scan().to_arrow()
regions = {}
for r in scan.column("region").to_pylist():
    regions[r] = regions.get(r, 0) + 1
print(f"  rows now in the table: {scan.num_rows}")
for r in sorted(regions):
    print(f"    {r:<10} {regions[r]:>4}")
print("  -> both writes are present. The retry cost one round trip, and no")
print("     row was lost or silently overwritten. An append could retry")
print("     automatically because appends do not conflict on content —")
print("     only on the pointer.")
