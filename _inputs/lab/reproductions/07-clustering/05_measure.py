"""Repro #7 — clustering: what the planner can skip, and why.

Run: docker exec spark-iceberg python3 /tmp/07_measure.py   (or `just m07-cluster`)

Takes a snapshot of the table's CURRENT layout: how many files, what range of
each column they cover, and how many the planner has to open for a point
lookup. Run it after each rewrite to compare layouts — the recipe runs it three
times (scattered, sorted, z-ordered) and that sequence is the whole repro.

Every number Module 07 quotes comes from here. Snapshot ids and byte sizes
regenerate on every run — never hardcode one.
"""
import struct
import sys

from pyiceberg.catalog.rest import RestCatalog

LABEL = sys.argv[1] if len(sys.argv) > 1 else "current layout"

cat = RestCatalog(
    "demo", uri="http://rest:8181", warehouse="s3://warehouse/",
    **{"s3.endpoint": "http://minio:9000",
       "s3.access-key-id": "admin", "s3.secret-access-key": "password"},
)
t = cat.load_table("db.clustering")

# Field ids come from the schema, never hardcoded — a schema edit would
# silently shift them and every bound below would decode as the wrong column.
FIELD = {f.name: f.field_id for f in t.schema().fields}
CUST, AMT = FIELD["customer_id"], FIELD["amt"]


def files_now():
    """De-duplicated by path: plan_files() can yield the same file twice."""
    out = {}
    for task in t.scan().plan_files():
        out[task.file.file_path] = task.file
    return out


def bounds(f, field_id, fmt):
    lo = f.lower_bounds.get(field_id)
    hi = f.upper_bounds.get(field_id)
    if lo is None or hi is None:
        return None
    return struct.unpack(fmt, lo)[0], struct.unpack(fmt, hi)[0]


def planned(row_filter):
    return len({x.file.file_path for x in t.scan(row_filter=row_filter).plan_files()})


files = files_now()
n = len(files)
rows = sum(f.record_count for f in files.values())
size = sum(f.file_size_in_bytes for f in files.values())

# ── LAYER 1: the layout ───────────────────────────────────────────────────
print(f"\n========== LAYER 1: LAYOUT — {LABEL} ==========")
print(f"  files: {n}   rows: {rows}   bytes: {size}")
print("  -> the row count never changes across this repro. Only which rows")
print("     share a file does.")

# ── LAYER 2: what each file's stats claim ─────────────────────────────────
print(f"\n========== LAYER 2: PER-FILE RANGES — {LABEL} ==========")
by_cust = sorted(files.values(),
                 key=lambda f: (bounds(f, CUST, "<i") or (0, 0))[0])
for f in by_cust:
    c = bounds(f, CUST, "<i")
    a = bounds(f, AMT, "<d")
    c_txt = f"{c[0]:>3}..{c[1]:>3}" if c else "  n/a"
    a_txt = f"{a[0]:>3.0f}..{a[1]:>3.0f}" if a else "  n/a"
    print(f"    {f.record_count:>4} rows   customer_id {c_txt}   amt {a_txt}")
cust_spans = [b[1] - b[0] for b in (bounds(f, CUST, "<i") for f in files.values()) if b]
amt_spans = [b[1] - b[0] for b in (bounds(f, AMT, "<d") for f in files.values()) if b]
if cust_spans:
    print(f"  -> customer_id span per file: min {min(cust_spans)}, max {max(cust_spans)}"
          f"  (column range is 0..999)")
if amt_spans:
    print(f"  -> amt span per file:         min {min(amt_spans):.0f}, "
          f"max {max(amt_spans):.0f}  (column range is 0..999)")
print("     A span near 999 means the file covers nearly the whole column, so")
print("     its min/max rules nothing out. That is what 'wide stats' means.")

# ── LAYER 3: what the planner can actually skip ───────────────────────────
print(f"\n========== LAYER 3: FILES PLANNED — {LABEL} ==========")
probes = [
    ("customer_id = 500", "customer_id = 500"),
    ("amt = 500", "amt = 500.0"),
]
for label, expr in probes:
    hit = planned(expr)
    skipped = n - hit
    pct = (100 * skipped / n) if n else 0
    print(f"  {label:<20} opens {hit} of {n} files   (skips {skipped}, {pct:.0f}%)")
print("  -> nothing was read to decide this. The planner compared the filter")
print("     against each file's min/max and ruled files out before opening any.")

# ── LAYER 4: the cost of the layout, not the data ─────────────────────────
print(f"\n========== LAYER 4: WHAT THIS COSTS A READER — {LABEL} ==========")
hit_cust = planned("customer_id = 500")
print(f"  a customer lookup touches {hit_cust} of {n} files")
if n:
    print(f"  which is {100 * hit_cust / n:.0f}% of the table's bytes for one customer's rows")
print("  -> identical rows, identical file count, identical stats machinery.")
print("     The only variable is which rows were written next to each other.")

# ── LAYER 5: how the current layout was produced ──────────────────────────
print(f"\n========== LAYER 5: PROVENANCE — {LABEL} ==========")
snap = t.current_snapshot()
op = getattr((snap.summary or {}).get("operation"), "value", "?")
print(f"  current snapshot op={op}   total snapshots: {len(t.metadata.snapshots)}")
order = t.sort_order()
if order and order.fields:
    print(f"  table sort-order id {order.order_id}: "
          f"{[(sf.source_id, str(sf.transform)) for sf in order.fields]}")
else:
    print("  table sort-order: unsorted (writes are not ordered on arrival)")
print("  -> every rewrite here is an ordinary commit (Module 02). Clustering is")
print("     not a mode the table is in; it is a property of the last write.")
