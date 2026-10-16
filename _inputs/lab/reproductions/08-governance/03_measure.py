"""Repro #8 — the price of a deleted row, and the metrics worth alerting on.

Run: docker exec spark-iceberg python3 /tmp/08_measure.py   (or `just m08-cost`)

Prices the Module 03 choice rather than restating it: bytes written per byte of
real change, files a reader must merge afterwards, and the storage that a
delete leaves behind. Run AFTER 02_delete.sql.

Every number Module 08 quotes comes from here. Byte sizes drift a little
between runs (parquet compression) — the ratios do not.
"""
from pyiceberg.catalog.rest import RestCatalog

cat = RestCatalog(
    "demo", uri="http://rest:8181", warehouse="s3://warehouse/",
    **{"s3.endpoint": "http://minio:9000",
       "s3.access-key-id": "admin", "s3.secret-access-key": "password"},
)
cow = cat.load_table("db.gov_cow")
mor = cat.load_table("db.gov_mor")


def op_of(snap) -> str:
    return getattr((snap.summary or {}).get("operation"), "value", "?") or ""


def live(t):
    """De-duplicated by path — plan_files() can yield a file more than once."""
    out = {}
    for task in t.scan().plan_files():
        out[task.file.file_path] = task.file
    return out


def num(snap, key, default=0):
    try:
        return int((snap.summary or {}).get(key, default))
    except (TypeError, ValueError):
        return default


# ── LAYER 1: what one row is worth ────────────────────────────────────────
print("\n========== LAYER 1: THE UNIT OF CHANGE ==========")
files = live(cow)
rows = sum(f.record_count for f in files.values())
size = sum(f.file_size_in_bytes for f in files.values())
per_row = size / rows if rows else 0
print(f"  copy-on-write table: {len(files)} files, {rows} rows, {size} bytes")
print(f"  -> about {per_row:.1f} bytes per row on disk")

# ── LAYER 2: write amplification ──────────────────────────────────────────
print("\n========== LAYER 2: WRITE AMPLIFICATION (copy-on-write) ==========")
dels = [s for s in cow.metadata.snapshots if op_of(s) in ("overwrite", "delete")]
if not dels:
    print("  no delete snapshot — run 02_delete.sql first")
else:
    d = dels[-1]
    added_rows = num(d, "added-records")
    removed_rows = num(d, "deleted-records")
    written = num(d, "added-files-size")
    print(f"  rows actually deleted:      1")
    print(f"  rows rewritten to do it:    {added_rows}")
    print(f"  data files rewritten:       {num(d, 'deleted-data-files')}")
    print(f"  bytes written:              {written}")
    if per_row:
        print(f"  -> {written / per_row:,.0f}x amplification by bytes "
              f"({written} written for ~{per_row:.0f} bytes of change)")
    print(f"  -> {added_rows}x amplification by rows: the unit of rewrite is a")
    print(f"     FILE, not a row. Deleting one row rewrote the {removed_rows} rows")
    print("     that happened to share its file.")

# ── LAYER 3: read amplification ───────────────────────────────────────────
print("\n========== LAYER 3: READ AMPLIFICATION (merge-on-read) ==========")
snap = mor.current_snapshot()
total_del = num(snap, "total-delete-files")
total_data = num(snap, "total-data-files")
tasks = list(mor.scan().plan_files())
merging = [x for x in tasks if getattr(x, "delete_files", None)]
mor_dels = [s for s in mor.metadata.snapshots if op_of(s) in ("overwrite", "delete")]
if mor_dels:
    each = num(mor_dels[-1], "added-files-size")
    print(f"  bytes written per delete:   {each}   (vs {num(dels[-1], 'added-files-size') if dels else '?'} for copy-on-write)")
print(f"  delete files now live:      {total_del}   over {total_data} data files")
print(f"  scan tasks that must merge: {len(merging)} of {len(tasks)}")
print("  -> the write got cheap and the read got a job. Every scan of those")
print("     files now merges tombstones before returning a row, on every query,")
print("     until compaction applies them (Module 05).")

# ── LAYER 4: what the delete left on disk ─────────────────────────────────
print("\n========== LAYER 4: STORAGE AFTER THE DELETE ==========")
for name, t in (("copy-on-write", cow), ("merge-on-read", mor)):
    lv = live(t)
    live_bytes = sum(f.file_size_in_bytes for f in lv.values())
    referenced = set()
    for s in t.metadata.snapshots:
        try:
            for task in t.scan(snapshot_id=s.snapshot_id).plan_files():
                referenced.add(task.file.file_path)
        except Exception:
            continue
    retained = 0
    for p in referenced:
        if p in lv:
            continue
        try:
            if t.io.new_input(p).exists():
                retained += 1
        except Exception:
            pass
    print(f"  {name:<14} live {len(lv)} files / {live_bytes} bytes  "
          f"+ {retained} superseded file(s) still referenced by older snapshots")
print("  -> a delete never shrinks storage on its own. The old file is kept for")
print("     the snapshots that cite it, and only expiry reclaims it (Module 06).")

# ── LAYER 5: the numbers worth alerting on ────────────────────────────────
print("\n========== LAYER 5: TABLE HEALTH METRICS ==========")
for name, t in (("copy-on-write", cow), ("merge-on-read", mor)):
    lv = live(t)
    n = len(lv)
    b = sum(f.file_size_in_bytes for f in lv.values())
    r = sum(f.record_count for f in lv.values())
    sn = t.current_snapshot()
    print(f"  {name}")
    print(f"    data files            {n}")
    print(f"    avg file size         {b // n if n else 0} bytes")
    print(f"    delete files          {num(sn, 'total-delete-files')}")
    print(f"    snapshots retained    {len(t.metadata.snapshots)}")
    print(f"    rows                  {r}")
print("  -> none of these is a cost in itself. They are the inputs to one:")
print("     small average file size means planning overhead (Module 05), delete")
print("     files mean read amplification, retained snapshots mean storage you")
print("     are paying for (Module 06). Cost governance is watching the inputs.")
