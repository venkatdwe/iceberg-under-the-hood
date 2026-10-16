"""Walk the Iceberg metadata tree from real files — pyiceberg + pyarrow.
Run inside spark-iceberg: docker exec spark-iceberg python3 /tmp/03_walk.py
Walks the four layers top-down: snapshots -> manifest list -> manifests -> data files."""
import pyarrow.parquet as pq
from pyiceberg.catalog.rest import RestCatalog
from pyiceberg.conversions import from_bytes
from pyiceberg.io.pyarrow import PyArrowFileIO

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

print("\n========== LAYER 1: metadata.json -> SNAPSHOTS ==========")
print(f"current-snapshot-id = {tbl.metadata.current_snapshot_id}")
for s in tbl.metadata.snapshots:
    print(f"  snapshot {s.snapshot_id}  parent={s.parent_snapshot_id}  "
          f"op={s.summary.operation}  manifest_list={s.manifest_list.split('/')[-1]}")

cur = tbl.current_snapshot()
print(f"\n========== LAYER 2: MANIFEST LIST of current snapshot ==========")
print(f"(snapshot {cur.snapshot_id}'s manifest list -> the manifests it points to)")
manifests = cur.manifests(io)
import datetime as _dt
for m in manifests:
    # partition_summaries = the LEVEL-1 prune (min/max range per partition field)
    summ = [(ps.lower_bound, ps.upper_bound) for ps in (m.partitions or [])]
    print(f"  manifest {m.manifest_path.split('/')[-1]}  "
          f"added_files={m.added_files_count}  partition[min,max]={summ}")
    # Decode the raw bound alongside it. The narration walks this conversion
    # out loud ("little endian integer... twenty thousand six hundred
    # thirty-one... days since 1970 — June 27th"), but the viewer previously
    # saw only b'\x97P\x00\x00' and had nothing to check that claim against.
    # Keeping BOTH keeps the raw bytes as the teaching object while making
    # the decode verifiable on screen.
    for lo, hi in summ:
        try:
            lo_i = int.from_bytes(lo, "little")
            hi_i = int.from_bytes(hi, "little")
            epoch = _dt.date(1970, 1, 1)
            lo_d = epoch + _dt.timedelta(days=lo_i)
            hi_d = epoch + _dt.timedelta(days=hi_i)
            rng = f"{lo_i}" if lo_i == hi_i else f"{lo_i}..{hi_i}"
            dts = f"{lo_d}" if lo_d == hi_d else f"{lo_d}..{hi_d}"
            print(f"      decoded: event_date = {rng}  (days since 1970) = {dts}")
        except Exception:
            pass

print(f"\n========== LAYER 3: MANIFEST ENTRIES -> DATA FILES + per-file STATS ==========")
print("(per data file: record_count + lower/upper bounds = the LEVEL-2 prune)")
schema = tbl.schema()
for m in manifests:
    for entry in m.fetch_manifest_entry(io):
        d = entry.data_file
        print(f"  file {d.file_path.split('/')[-1]}")
        print(f"      records={d.record_count}  size={d.file_size_in_bytes}B  partition={d.partition}")
        print(f"      lower_bounds(raw by field-id)={dict(d.lower_bounds)}")
        print(f"      upper_bounds(raw by field-id)={dict(d.upper_bounds)}")
        # Decoded: the raw bounds above are the real on-disk bytes, but
        # nothing about them is human-legible on screen — a viewer can't
        # tell 'alice to carol' or '30.0 to 40.0' from a dict of field-id
        # -> bytes. from_bytes() applies the schema's own per-field type to
        # decode them, the same conversion the query engine performs.
        decoded = {
            schema.find_field(fid).name: (from_bytes(schema.find_field(fid).field_type, lo),
                                          from_bytes(schema.find_field(fid).field_type, hi))
            for fid, lo in sorted(d.lower_bounds.items())
            for hi in [d.upper_bounds[fid]]
        }
        pretty = "  ".join(f"{name}=[{lo},{hi}]" for name, (lo, hi) in decoded.items())
        print(f"      decoded: {pretty}")

print(f"\n========== LAYER 4: inside a PARQUET file (footer / row groups) ==========")
df = tbl.scan().plan_files()
one = next(iter(df))
path = one.file.file_path
print(f"opening: {path.split('/')[-1]}")
with io.new_input(path).open() as f:
    pf = pq.ParquetFile(f)
    md = pf.metadata
    print(f"  row_groups={md.num_row_groups}  rows={md.num_rows}  columns={md.num_columns}")
    rg = md.row_group(0)
    for i in range(rg.num_columns):
        col = rg.column(i)
        st = col.statistics
        print(f"    col '{col.path_in_schema}': type={col.physical_type} "
              f"compression={col.compression} encodings={col.encodings} "
              f"min={getattr(st,'min',None)} max={getattr(st,'max',None)}")

print(f"\n========== PRUNING PROOF: WHERE event_date = 2026-06-28 ==========")
from pyiceberg.expressions import EqualTo
import datetime
days = (datetime.date(2026, 6, 28) - datetime.date(1970, 1, 1)).days
planned = list(tbl.scan(row_filter=EqualTo("event_date", days)).plan_files())
print(f"data files the planner kept = {len(planned)} (of 2 total):")
for t in planned:
    print(f"  -> {t.file.file_path.split('/')[-1]}")
