"""Repro #0, step 1 — a Hive-style table is whatever is in the directory.

No catalog, no metadata, no commit: a directory of Parquet files, read as a
table. That is what Iceberg replaced, and the failure mode is one line long.

Run:  docker exec spark-iceberg python3 /tmp/00_hive_style.py
"""
import glob, shutil
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()
spark.sparkContext.setLogLevel("ERROR")

P = "/tmp/hive_demo"
shutil.rmtree(P, ignore_errors=True)

spark.range(1, 301).selectExpr("id", "'us' as region") \
     .write.mode("overwrite").parquet(P)

rows = spark.read.parquet(P).count()
files = len(glob.glob(P + "/*.parquet"))
print("=== HIVE-STYLE: the directory IS the table ===")
print(f"  rows in table      {rows}")
print(f"  files in directory {files}")

# Somebody's job drops one more file in. Nothing was committed. Nothing was
# told. There is no catalog to tell.
spark.range(1000, 1051).selectExpr("id", "'eu' as region") \
     .write.mode("append").parquet(P)

rows2 = spark.read.parquet(P).count()
files2 = len(glob.glob(P + "/*.parquet"))
print(f"  ...one file appears in the directory...")
print(f"  rows in table      {rows2}   <- grew by {rows2 - rows}, with no commit")
print(f"  files in directory {files2}")
print()
print("  The table changed because a FILE changed. Nobody approved it and")
print("  nothing recorded it. A half-finished job leaves a half-finished table.")
