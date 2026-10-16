-- Lab repro #14 — one table, every engine, and the moment they disagree.
--
-- The capstone. Modules 01-13 established that the data files are portable, the
-- catalog is an HTTP contract, and a rollback moves a branch ref. This puts all
-- three together and finds the seam.
--
-- Its own table, like every repro here. `db.interop` is created, written and
-- rolled back entirely within this module — an earlier probe used module 09's
-- table and could not be re-run once the lab was rebuilt.
--
-- Three inserts so there is a history to roll back into.

CREATE DATABASE IF NOT EXISTS demo.db;

DROP TABLE IF EXISTS demo.db.interop;
CREATE TABLE demo.db.interop (id bigint, region string, amount int)
USING iceberg
TBLPROPERTIES ('format-version'='2', 'write.distribution-mode'='none');

INSERT INTO demo.db.interop
  SELECT id, 'us-east', CAST(pmod(id * 7919, 500) AS int) FROM range(1, 101);
INSERT INTO demo.db.interop
  SELECT id, 'us-west', CAST(pmod(id * 7919, 500) AS int) FROM range(101, 201);
INSERT INTO demo.db.interop
  SELECT id, 'eu-west', CAST(pmod(id * 7919, 500) AS int) FROM range(201, 301);
