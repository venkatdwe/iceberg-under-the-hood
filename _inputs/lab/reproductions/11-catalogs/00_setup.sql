-- Repro #11, step 0 — this module's own table.
--
-- Every other repro here creates what it reads. This one originally did not: it
-- explored whatever tables happened to be in the catalog and had DuckDB read
-- module 08's `db.gov_cow`. That coupling broke the moment the lab was torn
-- down and rebuilt — the catalog still LISTS the old tables, but loadTable
-- returns 404 for them, so the layers that follow died on a stale name.
--
-- A repro that depends on another module's leftovers is not reproducible. This
-- table is small, disposable, and belongs to module 11.

CREATE DATABASE IF NOT EXISTS demo.db;

DROP TABLE IF EXISTS demo.db.catalog_demo;
CREATE TABLE demo.db.catalog_demo (id bigint, region string)
USING iceberg
TBLPROPERTIES ('format-version'='2', 'write.distribution-mode'='none');

INSERT INTO demo.db.catalog_demo
  SELECT id, CASE WHEN pmod(id, 3) = 0 THEN 'us-east'
                  WHEN pmod(id, 3) = 1 THEN 'us-west'
                  ELSE 'eu-west' END
  FROM range(1, 301);
