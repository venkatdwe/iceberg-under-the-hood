"""Inspect Iceberg metadata tables via pyiceberg (works where Spark metadata-tables
fail on the REST fixture). Shows EVERY column of each metadata table.
Run: docker exec spark-iceberg python3 /tmp/04_inspect.py"""
from pyiceberg.catalog.rest import RestCatalog

cat = RestCatalog("demo", uri="http://rest:8181", warehouse="s3://warehouse/",
                  **{"s3.endpoint": "http://minio:9000",
                     "s3.access-key-id": "admin", "s3.secret-access-key": "password"})
t = cat.load_table("db.events")

# The metadata tables pyiceberg can synthesize. Same data Spark's .snapshots etc. expose.
TABLES = ["snapshots", "manifests", "entries", "refs", "partitions", "history", "metadata_log_entries"]

for name in TABLES:
    method = getattr(t.inspect, name, None)
    if method is None:
        print(f"\n===== {name}: not available in this pyiceberg version =====")
        continue
    try:
        arrow = method()
    except Exception as e:
        print(f"\n===== {name}: ERROR {e} =====")
        continue
    print(f"\n===== {name}  ({arrow.num_rows} rows) =====")
    print("columns:", arrow.column_names)
    for i, row in enumerate(arrow.to_pylist()):
        print(f"  [{i}] " + "  ".join(f"{k}={row[k]!r}" for k in arrow.column_names))
