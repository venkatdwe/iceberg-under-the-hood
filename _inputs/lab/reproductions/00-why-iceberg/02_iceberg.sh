#!/bin/bash
# Repro #0, step 2 — an Iceberg table is what the metadata says it is.
#
# Same trick as step 1: put a file in the table's data directory. This time the
# table does not move, because a file is only in the table once a commit says so.
#
# Run from the HOST (uses the lab's mc container):  bash 02_iceberg.sh
set -u
Q() { docker exec spark-iceberg spark-sql -e "$1" 2>/dev/null | grep -E '^[0-9]+$' | head -1; }
NF() { docker exec mc mc ls minio/warehouse/db/ice_demo/data/ 2>/dev/null | wc -l | tr -d ' '; }

# DROP TABLE leaves the data files behind, so a re-run would count stale files
# from the previous run and the "one file appeared" step would look like a no-op.
# Clear the prefix in object storage first.
docker exec spark-iceberg spark-sql -e "DROP TABLE IF EXISTS demo.db.ice_demo;" >/dev/null 2>&1
docker exec mc mc rm --recursive --force minio/warehouse/db/ice_demo/ >/dev/null 2>&1 || true

docker exec spark-iceberg spark-sql -e "
  CREATE TABLE demo.db.ice_demo (id bigint, region string) USING iceberg;
  INSERT INTO demo.db.ice_demo SELECT id, 'us' FROM range(1, 301);" >/dev/null 2>&1

echo "=== ICEBERG: the metadata IS the table ==="
echo "  rows in table      $(Q 'SELECT count(*) FROM demo.db.ice_demo;')"
echo "  files in directory $(NF)"

SRC=$(docker exec mc mc ls minio/warehouse/db/ice_demo/data/ 2>/dev/null | head -1 | awk '{print $NF}')
STRAY="99999-stray-$(date +%s)-00001.parquet"
docker exec mc mc cp "minio/warehouse/db/ice_demo/data/$SRC" \
                     "minio/warehouse/db/ice_demo/data/$STRAY" >/dev/null 2>&1

echo "  ...the same file trick, into the table's own data directory..."
echo "  rows in table      $(Q 'SELECT count(*) FROM demo.db.ice_demo;')   <- UNCHANGED"
echo "  files in directory $(NF)"
echo
echo "  The file is right there on disk and it is not in the table, because"
echo "  no commit added it. That is the whole difference."
