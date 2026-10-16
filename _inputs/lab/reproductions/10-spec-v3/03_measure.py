"""Repro #10 — what a v3 delete costs, and who can read the result.

Run: docker exec spark-iceberg python3 /tmp/10_measure.py   (AFTER 02_delete.sql)

Two tables, identical but for format-version, both merge-on-read, same single
row deleted from each. The first three layers price the deletion vector. The
fourth is the one that matters in production: the same pyiceberg that reads the
v2 table raises on the v3 one, because the deletion vector is a Puffin file and
its FileFormat enum has no entry for PUFFIN.

Every failure here is caught and REPORTED rather than allowed to end the script.
The client failing is the finding, not an error in the repro.
"""
from pyiceberg.catalog.rest import RestCatalog

cat = RestCatalog(
    "demo", uri="http://rest:8181", warehouse="s3://warehouse/",
    **{"s3.endpoint": "http://minio:9000",
       "s3.access-key-id": "admin", "s3.secret-access-key": "password"},
)

TABLES = [("v2  (position deletes)", "db.dv_v2"),
          ("v3  (deletion vector)", "db.dv_v3")]


def summ(snap, key):
    """Snapshot summary values arrive as enums for some keys, strings for others."""
    v = (snap.summary or {}).get(key)
    return getattr(v, "value", v)


loaded = []
for label, name in TABLES:
    t = cat.load_table(name)
    loaded.append((label, name, t))

# ── LAYER 1: one variable ─────────────────────────────────────────────────
print("\n========== LAYER 1: SAME TABLE, TWO FORMAT VERSIONS ==========")
for label, name, t in loaded:
    props = dict(t.metadata.properties or {})
    print(f"  {label}")
    print(f"    format-version      {t.metadata.format_version}")
    print(f"    write.delete.mode   {props.get('write.delete.mode')}")
print("  -> merge-on-read on BOTH. A v3 table with the default delete mode")
print("     still rewrites whole files and produces no deletion vector, which")
print("     is the most likely way to 'adopt v3' and measure no change at all.")

# ── LAYER 2: what the delete cost ─────────────────────────────────────────
print("\n========== LAYER 2: BYTES WRITTEN TO DELETE ONE ROW ==========")
costs = {}
for label, name, t in loaded:
    snap = t.current_snapshot()
    written = summ(snap, "added-files-size")
    costs[name] = int(written) if written is not None else None
    print(f"  {label}")
    print(f"    operation           {summ(snap, 'operation')}")
    print(f"    bytes written       {written}")
    print(f"    delete files        {summ(snap, 'total-delete-files')}")
    print(f"    position deletes    {summ(snap, 'total-position-deletes')}")
    print(f"    data files          {summ(snap, 'total-data-files')}")
a, b = costs.get("db.dv_v2"), costs.get("db.dv_v3")
if a and b:
    print(f"  -> v3 wrote {b} bytes where v2 wrote {a} — {a / b:.1f}x smaller,")
    print("     for the identical row on an identical table.")

# ── LAYER 3: what the delete file actually is ─────────────────────────────
print("\n========== LAYER 3: WHAT GOT WRITTEN ==========")
for label, name, t in loaded:
    try:
        paths = {}
        for task in t.scan().plan_files():
            for df in (getattr(task, "delete_files", None) or []):
                paths[df.file_path] = str(df.file_format)
        if paths:
            for p, fmt in paths.items():
                print(f"  {label}:  {fmt:<8} {p.rsplit('/', 1)[-1]}")
        else:
            print(f"  {label}:  no delete files attached to any scan task")
    except Exception as exc:
        print(f"  {label}:  cannot enumerate — {type(exc).__name__}: {str(exc)[:60]}")

# ── LAYER 4: the part that decides whether you adopt ──────────────────────
print("\n========== LAYER 4: CAN YOUR CLIENT READ IT? ==========")
import pyiceberg
print(f"  reader: pyiceberg {pyiceberg.__version__}")
for label, name, t in loaded:
    try:
        n = t.scan().to_arrow().num_rows
        print(f"  {label}:  OK — {n} rows readable")
    except Exception as exc:
        print(f"  {label}:  FAILED — {type(exc).__name__}: {str(exc)[:70]}")
print("  -> Spark wrote both tables happily. The Python client in the SAME")
print("     container reads one and raises on the other, because a deletion")
print("     vector is a Puffin file and this version's FileFormat enum has no")
print("     entry for it.")
print("     That is the real risk of adopting v3, and it is not the concept —")
print("     it is ecosystem lag. The engine that writes and the client that")
print("     reads are versioned separately, so a v3 table is readable only by")
print("     the part of your stack that has caught up. A table one tool writes")
print("     and another cannot open is worse than not adopting yet.")
