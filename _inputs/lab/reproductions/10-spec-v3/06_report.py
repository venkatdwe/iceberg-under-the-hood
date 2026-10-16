"""Repro #10, step 6 — report what the in-place upgrade actually did.

Read through pyiceberg: Spark metadata tables do not resolve against this
REST catalog.
"""
from pyiceberg.catalog import load_catalog

cat = load_catalog("demo", **{
    "type": "rest", "uri": "http://iceberg-rest:8181",
    "s3.endpoint": "http://minio:9000",
    "s3.access-key-id": "admin", "s3.secret-access-key": "password",
})
t = cat.load_table("db.dv_upgrade")

print("=== AFTER IN-PLACE UPGRADE ===")
print(f"  format-version      {t.metadata.format_version}")
print(f"  write.delete.mode   {t.properties.get('write.delete.mode')}")
print()
print("  seq  operation  data-files  delete-files  dvs")
for s in t.metadata.snapshots:
    p = s.summary._additional_properties
    print(f"  {s.sequence_number:>3}  {s.summary.operation.value:<9}"
          f"  {p.get('total-data-files','-'):>10}"
          f"  {p.get('total-delete-files','-'):>12}"
          f"  {p.get('added-dvs','-'):>3}")
