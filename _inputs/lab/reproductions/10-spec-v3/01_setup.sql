-- Lab repro #10 — spec v3 deletion vectors, and the client that cannot read them.
--
-- Two tables identical in every respect except format-version, so the version is
-- the only variable. Both merge-on-read, because that is load-bearing: a v3
-- table with the default write.delete.mode still does copy-on-write and produces
-- NO deletion vector at all. "We upgraded to v3" is exactly what a team says
-- before measuring that nothing changed.
--
-- 500 rows with a 50-byte payload. Small on purpose — the interesting number is
-- the size of the DELETE, not the size of the table.
--
-- Touches only db.dv_v2 and db.dv_v3. Modules 06-09 and 11 own everything else.

CREATE DATABASE IF NOT EXISTS demo.db;

DROP TABLE IF EXISTS demo.db.dv_v2;
CREATE TABLE demo.db.dv_v2 (id bigint, val string)
USING iceberg
TBLPROPERTIES ('format-version'='2',
               'write.delete.mode'='merge-on-read',
               'write.distribution-mode'='none');

DROP TABLE IF EXISTS demo.db.dv_v3;
CREATE TABLE demo.db.dv_v3 (id bigint, val string)
USING iceberg
TBLPROPERTIES ('format-version'='3',
               'write.delete.mode'='merge-on-read',
               'write.distribution-mode'='none');

INSERT INTO demo.db.dv_v2 SELECT id, repeat('x', 50) FROM range(1, 501);
INSERT INTO demo.db.dv_v3 SELECT id, repeat('x', 50) FROM range(1, 501);
