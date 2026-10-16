-- Lab repro #5 — the small-file problem, created the way it actually happens.
--
-- Nobody sets out to write 1-row files. They arrive from a streaming or CDC
-- feed that commits often, and each commit writes at least one file. Eight
-- commits here stand in for eight minutes of a feed that never stops.
--
-- Unpartitioned on purpose: the small-file problem is not about partitioning,
-- and adding it would let a viewer blame the layout instead of the commit rate.

CREATE DATABASE IF NOT EXISTS demo.db;

DROP TABLE IF EXISTS demo.db.trickle;
CREATE TABLE demo.db.trickle (
  id       bigint,
  ts       timestamp,
  customer string,
  amt      double
)
USING iceberg
TBLPROPERTIES ('format-version'='2');

-- Eight separate commits. Each one is a snapshot, and each writes its own file.
INSERT INTO demo.db.trickle VALUES (1, TIMESTAMP'2026-07-01 10:00:00','alice',10.0);
INSERT INTO demo.db.trickle VALUES (2, TIMESTAMP'2026-07-01 10:05:00','bob',  20.0);
INSERT INTO demo.db.trickle VALUES (3, TIMESTAMP'2026-07-01 10:10:00','carol',30.0);
INSERT INTO demo.db.trickle VALUES (4, TIMESTAMP'2026-07-01 10:15:00','dave', 40.0);
INSERT INTO demo.db.trickle VALUES (5, TIMESTAMP'2026-07-01 10:20:00','erin', 50.0);
INSERT INTO demo.db.trickle VALUES (6, TIMESTAMP'2026-07-01 10:25:00','frank',60.0);
INSERT INTO demo.db.trickle VALUES (7, TIMESTAMP'2026-07-01 10:30:00','grace',70.0);
INSERT INTO demo.db.trickle VALUES (8, TIMESTAMP'2026-07-01 10:35:00','heidi',80.0);
