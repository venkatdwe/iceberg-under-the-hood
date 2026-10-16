"""Compare what CoW vs MoR physically wrote for the SAME delete.
Run: docker exec spark-iceberg python3 /tmp/03_compare.py"""
from pyiceberg.catalog.rest import RestCatalog

cat = RestCatalog("demo", uri="http://rest:8181", warehouse="s3://warehouse/",
                  **{"s3.endpoint": "http://minio:9000",
                     "s3.access-key-id": "admin", "s3.secret-access-key": "password"})

CONTENT = {0: "DATA", 1: "POSITION-DELETE", 2: "EQUALITY-DELETE"}
STATUS = {0: "EXISTING", 1: "ADDED", 2: "DELETED"}
KEYS = ["added-data-files", "deleted-data-files", "added-records", "deleted-records",
        "added-delete-files", "added-position-deletes",
        "total-data-files", "total-delete-files", "total-records"]

def report(tbl_name):
    t = cat.load_table(tbl_name)
    print(f"\n############### {tbl_name} ###############")

    snaps = t.inspect.snapshots().to_pylist()
    print(f"snapshots: {len(snaps)}  (insert, then delete)")
    delete_commit = dict(snaps[-1]["summary"])
    print(f"the DELETE commit's summary:")
    for k in KEYS:
        if k in delete_commit:
            print(f"    {k:24} = {delete_commit[k]}")

    print("files this snapshot's manifests reference (status = ADDED/EXISTING/DELETED):")
    for e in t.inspect.entries().to_pylist():
        d = e["data_file"]
        kind = CONTENT.get(d["content"], d["content"])
        st = STATUS.get(e["status"], e["status"])
        name = d["file_path"].split("/")[-1]
        print(f"    [{st:8}] [{kind:15}] records={d['record_count']}  {name}")

    rows = t.scan().to_arrow().num_rows
    print(f"rows a reader sees: {rows}")

report("db.events_cow")
report("db.events_mor")

print("\n=================== THE CONTRAST ===================")
print("CoW delete: rewrote the data file (added 1 data file, deleted 1) — reads stay clean, write paid.")
print("MoR delete: wrote a POSITION-DELETE tombstone — data file untouched, write cheap, every read must merge it.")
