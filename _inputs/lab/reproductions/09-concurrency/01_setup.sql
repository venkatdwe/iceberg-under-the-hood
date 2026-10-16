-- Lab repro #9 — two writers, one table, and getting back from a bad commit.
--
-- Module 01 showed that a commit is a pointer swap on the metadata tree. This
-- is what that buys you when two writers race, and what it costs when one of
-- them was wrong.
--
-- One table, db.concurrent. Deliberately small and deliberately boring: the
-- subject here is the COMMIT PROTOCOL, not the data, and a large table would
-- only add noise to the snapshot chain the module has to read on screen.
--
-- Touches nothing else. Modules 06, 07 and 08 own db.lifecycle, db.trickle,
-- db.evolve, db.events, db.clustering, db.gov_cow and db.gov_mor.

CREATE DATABASE IF NOT EXISTS demo.db;

DROP TABLE IF EXISTS demo.db.concurrent;
CREATE TABLE demo.db.concurrent (id bigint, region string, amount int)
USING iceberg
TBLPROPERTIES ('format-version'='2',
               'write.distribution-mode'='none');

-- Three separate commits, so there is a real history to roll back into and
-- time-travel across. One INSERT of 300 rows would produce one snapshot and
-- nothing to demonstrate.
INSERT INTO demo.db.concurrent
  SELECT id, 'us-east', CAST(pmod(id * 7919, 500) AS int) FROM range(1, 101);
INSERT INTO demo.db.concurrent
  SELECT id, 'us-west', CAST(pmod(id * 7919, 500) AS int) FROM range(101, 201);
INSERT INTO demo.db.concurrent
  SELECT id, 'eu-west', CAST(pmod(id * 7919, 500) AS int) FROM range(201, 301);
