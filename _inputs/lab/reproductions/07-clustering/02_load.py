"""Repro #7, step 1 — write six scattered files.

Run: docker exec spark-iceberg python3 /tmp/07_load.py

Written through Spark's DataFrame API rather than INSERT ... SELECT because
`coalesce(1)` is what forces one output file per commit. Without it Spark
splits each batch across several files and partially orders them on the way,
which quietly improves the "bad" layout and shrinks the contrast this repro
is built to show.
"""
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()

BATCHES = [(1, 1001), (1001, 2001), (2001, 3001),
           (3001, 4001), (4001, 5001), (5001, 6001)]

for lo, hi in BATCHES:
    (spark.range(lo, hi)
          .selectExpr(
              "id",
              # independent of id and of each other — see 01_setup.sql
              "CAST(pmod(id * 7919, 1000) AS int)      as customer_id",
              "CAST(pmod(id * 104729, 1000) AS double) as amt")
          .coalesce(1)
          .writeTo("demo.db.clustering")
          .append())

print(f"wrote {len(BATCHES)} commits, 1000 rows each")
