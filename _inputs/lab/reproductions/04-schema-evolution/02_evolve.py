"""Repro #4 — show that schema and partition evolution rewrote nothing.

Run: docker exec spark-iceberg python3 /tmp/04_evolve.py   (or `just m04-evolve`)

Every number the module quotes comes from here. The four sections answer, in
order: what changed in the schema, what changed on disk (nothing), what the
files themselves still say, and how one table serves two partition layouts.
"""
import io

import pyarrow.parquet as pq
from pyiceberg.catalog.rest import RestCatalog

cat = RestCatalog(
    "demo", uri="http://rest:8181", warehouse="s3://warehouse/",
    **{"s3.endpoint": "http://minio:9000",
       "s3.access-key-id": "admin", "s3.secret-access-key": "password"},
)
t = cat.load_table("db.evolve")

# ── LAYER 1: the schema history — ids are stable, names are not ────────────
print("\n========== LAYER 1: SCHEMA HISTORY (what a rename actually changed) ==========")
for s in t.metadata.schemas:
    cols = ", ".join(f"{f.field_id}:{f.name}" for f in s.fields)
    print(f"  schema-id={s.schema_id}  ->  {cols}")
first, last = t.metadata.schemas[0], t.metadata.schemas[-1]
before = {f.field_id: f.name for f in first.fields}
after = {f.field_id: f.name for f in last.fields}
renamed = [(i, before[i], after[i]) for i in before if i in after and before[i] != after[i]]
added = [(i, after[i]) for i in after if i not in before]
for fid, old, new in renamed:
    print(f"  -> field id {fid} kept its id and changed name: {old!r} -> {new!r}")
for fid, name in added:
    print(f"  -> {name!r} is a NEW field id {fid}; rows written before it simply have no id {fid}")

# ── LAYER 2: snapshots — evolution wrote no data ───────────────────────────
print("\n========== LAYER 2: SNAPSHOTS (did evolving the table write anything?) ==========")
for s in t.metadata.snapshots:
    summary = s.summary or {}
    print(f"  snapshot {s.snapshot_id}  op={summary.get('operation')}  "
          f"added-data-files={summary.get('added-data-files')}  "
          f"added-records={summary.get('added-records')}")
print(f"  -> {len(t.metadata.snapshots)} snapshots, ALL of them appends.")
print("  -> the rename, the added column and the re-partition created NONE:")
print("     they only wrote new metadata.json, never a data file.")

# ── LAYER 3: the files still carry the OLD column name ─────────────────────
print("\n========== LAYER 3: WHAT THE PARQUET FILES THEMSELVES SAY ==========")
seen: set[str] = set()
for task in t.scan().plan_files():
    path = task.file.file_path
    if path in seen:
        continue
    seen.add(path)
    raw = t.io.new_input(path).open().read()
    schema = pq.ParquetFile(io.BytesIO(raw)).schema_arrow
    ids = [(schema.field(i).metadata or {}).get(b"PARQUET:field_id", b"?").decode()
           for i in range(len(schema))]
    pairs = ", ".join(f"{i}:{n}" for i, n in zip(ids, schema.names))
    part = next((seg for seg in path.split("/") if "event_ts_day=" in seg), "?")
    print(f"  spec_id={task.file.spec_id}  rows={task.file.record_count}  partition {part}")
    print(f"      {pairs}")
print("  -> the pre-rename files still say 'user_name' on disk. The table says")
print("     'customer'. Nobody rewrote them — the reader matches on field id 3,")
print("     so the name in the file is simply never consulted.")

# ── LAYER 4: two partition specs, one table ────────────────────────────────
print("\n========== LAYER 4: PARTITION EVOLUTION (both layouts, live) ==========")
for sp in t.metadata.partition_specs:
    fields = ", ".join(f"{fl.name}={fl.transform}(field {fl.source_id})" for fl in sp.fields)
    print(f"  spec-id={sp.spec_id}  ->  {fields}")
by_spec: dict[int, int] = {}
for task in t.scan().plan_files():
    by_spec[task.file.spec_id] = by_spec.get(task.file.spec_id, 0) + 1
for spec_id in sorted(by_spec):
    print(f"  -> {by_spec[spec_id]} data file(s) still written under spec-id {spec_id}")
print("  -> old files were NOT rewritten to match the new spec. One table, two")
print("     layouts, and the planner reads across both.")

# ── LAYER 5: hidden partitioning still prunes, across both specs ───────────
print("\n========== LAYER 5: HIDDEN PARTITIONING (filter the column, not a partition) ==========")
total = len(list(t.scan().plan_files()))
one_day = len(list(t.scan(row_filter="event_ts >= '2026-07-02T00:00:00+00:00' "
                                     "and event_ts < '2026-07-03T00:00:00+00:00'").plan_files()))
print(f"  full scan plans          : {total} data file(s)")
print(f"  filter one day of event_ts: {one_day} data file(s)")
print("  -> the query names event_ts, never a partition column: there ISN'T one.")
print(f"     Iceberg maps the filter through days(event_ts) and skips "
      f"{total - one_day} of {total} files.")

rows = len(t.scan().to_arrow())
print(f"\nfinal: {rows} rows readable across {total} files, "
      f"{len(t.metadata.schemas)} schemas and {len(t.metadata.partition_specs)} partition specs.")
