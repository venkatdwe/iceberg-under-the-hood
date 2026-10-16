-- Repro #10, step 6 — turning deletion vectors ON for a table you already have.
--
-- The setup scripts create v3 tables from scratch. The question a viewer
-- actually has is what to do with the v2 table already in production. This
-- upgrades one in place and proves the next delete takes the vector path.
--
-- NOTE ON ROW COUNT: 1,000 rows across several data files is load-bearing.
-- A tiny table lands one row per file, and deleting a row then drops the whole
-- file (deleted-data-files=1, total-delete-files=0) — no vector is written and
-- the demo silently measures the wrong thing.

DROP TABLE IF EXISTS db.dv_upgrade;

-- An ordinary v2 table, defaults everywhere. This is the "before".
CREATE TABLE db.dv_upgrade (id BIGINT, v STRING) USING iceberg
  TBLPROPERTIES ('format-version'='2');

INSERT INTO db.dv_upgrade SELECT id, CAST(id AS STRING) FROM range(1000);

-- The upgrade. BOTH properties: the version alone still copy-on-writes.
ALTER TABLE db.dv_upgrade SET TBLPROPERTIES (
  'format-version'    = '3',
  'write.delete.mode' = 'merge-on-read'
);

-- One row. This is the delete that should now write a vector instead of
-- rewriting the data file.
DELETE FROM db.dv_upgrade WHERE id = 500;
