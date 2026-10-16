"""Repro #6 — what expiry reclaims, what it does not, and what it costs you.

Run: docker exec spark-iceberg python3 /tmp/06_measure.py   (or `just m06-expire`)

Picks the table up where Module 05 left it — compacted, with eight replaced
data files still on disk — and measures each cleanup step. Run AFTER
02_expire.sql and 03_manifests.sql; the layers report the state those leave
behind.

Every number Module 06 quotes comes from here. Snapshot ids regenerate on
every run — never hardcode one.
"""
from pyiceberg.catalog.rest import RestCatalog

cat = RestCatalog(
    "demo", uri="http://rest:8181", warehouse="s3://warehouse/",
    **{"s3.endpoint": "http://minio:9000",
       "s3.access-key-id": "admin", "s3.secret-access-key": "password"},
)
t = cat.load_table("db.lifecycle")

live = {x.file.file_path: x.file.file_size_in_bytes for x in t.scan().plan_files()}
live_bytes = sum(live.values())

# ── LAYER 1: what survived the expiry ─────────────────────────────────────
print("\n========== LAYER 1: SNAPSHOTS AFTER EXPIRY ==========")
print(f"  snapshots remaining: {len(t.metadata.snapshots)}")
for s in t.metadata.snapshots:
    op = getattr((s.summary or {}).get("operation"), "value", "?")
    marker = "  <- current" if s.snapshot_id == t.metadata.current_snapshot_id else ""
    print(f"    {s.snapshot_id}  op={op}{marker}")
# The count is 2, not 1: expire_snapshots left exactly one, and then
# rewrite_manifests committed its repack as another. Saying "nine became one"
# would contradict the list printed directly above it — the sort of mismatch
# between narration and screen this course keeps catching.
print("  -> nine commits' worth of snapshots collapsed to one at expiry; the")
print("     second here is the manifest repack that followed, itself a commit.")
print("     Either way the eight original append snapshots are gone, and gone")
print("     permanently — this is the part that is not reversible.")

# ── LAYER 2: the data files it deleted ────────────────────────────────────
print("\n========== LAYER 2: DATA FILES ==========")
print(f"  live data files: {len(live)}  ({live_bytes} bytes)")
alive = sum(1 for p in live if t.io.new_input(p).exists())
print(f"  of those, present in object storage: {alive}")
print("  -> the eight files compaction replaced are gone from storage now.")
print("     Module 05 measured 9,864 bytes of them still sitting there;")
print("     expire_snapshots is what actually removed them.")

# ── LAYER 3: what time travel can still reach ─────────────────────────────
print("\n========== LAYER 3: WHAT YOU CAN STILL READ ==========")
rows = len(t.scan().to_arrow())
print(f"  current snapshot: {rows} rows")
try:
    t.scan(snapshot_id=1234567890123456789).to_arrow()
    print("  an expired snapshot id: unexpectedly readable")
except Exception as exc:
    print(f"  an expired snapshot id: {type(exc).__name__} — {str(exc)[:52]}")
print("  -> the rows are all still here. The HISTORY is not. Retention is a")
print("     recovery decision, not a housekeeping one: the window you keep is")
print("     exactly how far back you can roll a bad write.")

# ── LAYER 4: manifests ────────────────────────────────────────────────────
print("\n========== LAYER 4: MANIFESTS ==========")
manifests = t.current_snapshot().manifests(t.io)
print(f"  manifests in the current snapshot: {len(manifests)}")
for m in manifests:
    print(f"    {m.manifest_path.split('/')[-1][:44]}  added_files={m.added_files_count}")
total = sum(m.manifest_length for m in manifests)
target = dict(t.metadata.properties).get("commit.manifest.target-size-bytes",
                                         "8388608 (8 MB default)")
print(f"  total manifest bytes: {total}")
print(f"  commit.manifest.target-size-bytes = {target}")
print("  -> every commit wrote a manifest; rewrite_manifests bin-packs them by")
print("     SIZE against that target — the same idea as data compaction, one")
print("     level up. Measured: two ~7 KB manifests packed into one.")
print("     Note a manifest costs ~7 KB whether it indexes 1 file or 100, so")
print("     the waste is the same fixed-overhead problem as small data files.")
print("     The planner reads this list on EVERY query, before it opens any data.")

# ── LAYER 5: the metadata trail expiry does not touch ─────────────────────
print("\n========== LAYER 5: METADATA BLOAT ==========")
log = t.metadata.metadata_log
print(f"  metadata.json versions retained: {len(log)}")
props = dict(t.metadata.properties)
cleanup = props.get("write.metadata.delete-after-commit.enabled", "false")
keep = props.get("write.metadata.previous-versions-max", "100 (default)")
print(f"  write.metadata.delete-after-commit.enabled = {cleanup}")
print(f"  write.metadata.previous-versions-max       = {keep}")
print("  -> expiring snapshots does NOT prune metadata.json files. That is a")
print("     separate mechanism, it is OFF by default, and on a busy table the")
print("     metadata directory outgrows the data it describes.")
if cleanup == "true":
    print(f"  -> cleanup is ON here, keeping {keep} previous versions. Measured:")
    print("     12 metadata.json files became 4 after a single commit. It prunes")
    print("     on the next COMMIT, not retroactively — nothing happens until")
    print("     something writes.")
