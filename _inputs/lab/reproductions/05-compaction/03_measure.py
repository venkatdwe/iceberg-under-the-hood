"""Repro #5 — what the small-file problem costs, and what compaction returns.

Run: docker exec spark-iceberg python3 /tmp/05_measure.py   (or `just m05-compact`)

Reads both sides of the compaction from the table's own history, so the
before/after comparison is measured rather than remembered: the REPLACE
snapshot's parent IS the pre-compaction state, and pyiceberg can scan it
directly.

Every number Module 05 quotes comes from here. Snapshot ids regenerate on
every run — never hardcode one.
"""
from pyiceberg.catalog.rest import RestCatalog

cat = RestCatalog(
    "demo", uri="http://rest:8181", warehouse="s3://warehouse/",
    **{"s3.endpoint": "http://minio:9000",
       "s3.access-key-id": "admin", "s3.secret-access-key": "password"},
)
t = cat.load_table("db.trickle")


def op_of(snap) -> str:
    """Operation is an enum; .value is the string the spec uses."""
    return getattr((snap.summary or {}).get("operation"), "value", "") or ""


def files_at(snapshot_id=None):
    scan = t.scan(snapshot_id=snapshot_id) if snapshot_id else t.scan()
    seen = {}
    for task in scan.plan_files():
        seen[task.file.file_path] = (task.file.record_count, task.file.file_size_in_bytes)
    return seen


# ── LAYER 1: how the mess is made — one commit per file ───────────────────
print("\n========== LAYER 1: EIGHT COMMITS, EIGHT FILES ==========")
for s in t.metadata.snapshots:
    su = s.summary or {}
    print(f"  op={op_of(s):<8} added={su.get('added-data-files')}  "
          f"deleted={su.get('deleted-data-files') or 0}  "
          f"total-data-files={su.get('total-data-files')}")
print("  -> nobody chose to write 1-row files. A feed that commits often does")
print("     it for you: every commit writes at least one file.")

compaction = next((s for s in t.metadata.snapshots if op_of(s) == "replace"), None)
if compaction is None:
    raise SystemExit("no compaction snapshot — run 02_compact.sql first")

before = files_at(compaction.parent_snapshot_id)
after = files_at()
b_bytes = sum(sz for _, sz in before.values())
a_bytes = sum(sz for _, sz in after.values())
b_rows = sum(r for r, _ in before.values())

# ── LAYER 2: the cost is overhead, not data ───────────────────────────────
print("\n========== LAYER 2: WHAT EIGHT TINY FILES ACTUALLY COST ==========")
for i, (rows, size) in enumerate(sorted(before.values()), 1):
    print(f"  file {i}: {rows} row   {size:5d} bytes")
print(f"  -> {len(before)} files, {b_bytes} bytes, for {b_rows} rows.")
print("     A parquet file carries a footer, a schema and column metadata")
print("     whatever it holds — so a 1-row file is almost entirely overhead.")

# ── LAYER 3: compaction is a normal commit ────────────────────────────────
su = compaction.summary or {}
print("\n========== LAYER 3: COMPACTION IS A COMMIT, NOT A MUTATION ==========")
print(f"  snapshot {compaction.snapshot_id}  op={op_of(compaction)}")
print(f"    added-data-files   = {su.get('added-data-files')}")
print(f"    deleted-data-files = {su.get('deleted-data-files')}")
print(f"    total-data-files   = {su.get('total-data-files')}")
print("  -> it did not edit anything. It wrote a replacement and swapped the")
print("     pointer, exactly like the writes in Module 02.")

# ── LAYER 4: the payoff ───────────────────────────────────────────────────
print("\n========== LAYER 4: SAME ROWS, ONE FILE ==========")
for rows, size in after.values():
    print(f"  file 1: {rows} rows  {size} bytes")
saved = 100 * (b_bytes - a_bytes) / b_bytes if b_bytes else 0
ratio = b_bytes / a_bytes if a_bytes else 0
print(f"  -> {b_bytes} bytes became {a_bytes}: {ratio:.1f}x smaller, "
      f"{saved:.0f}% of the original was per-file overhead.")
print("     The data never changed. Only the number of files did.")

# ── LAYER 5: the bill compaction leaves behind ────────────────────────────
print("\n========== LAYER 5: THE OLD FILES ARE STILL THERE ==========")
alive = sum(1 for p in before if t.io.new_input(p).exists())
old_rows = len(t.scan(snapshot_id=compaction.parent_snapshot_id).to_arrow())
print(f"  old data files still in object storage: {alive} of {len(before)}")
print(f"  time travel to the pre-compaction snapshot still returns {old_rows} rows")
print(f"  -> storage right now is {b_bytes} + {a_bytes} = {b_bytes + a_bytes} bytes,")
print("     MORE than before you compacted. Compaction stops referencing the old")
print("     files; it does not delete them. Reclaiming that is expire-snapshots,")
print("     and that is Module 06.")
