-- Lab repro #6 — rebuild exactly where Module 05 ended, then clean it up.
--
-- Module 05 left the table with eight orphaned data files and MORE storage
-- than before it compacted. This repro starts from that state deliberately:
-- the whole point of Module 06 is that compaction hands you a bill, and this
-- is where you pay it.
--
-- Eight trickle commits, then compaction — identical to repro #5's setup, so
-- the two modules describe the same table at two points in its life.

CREATE DATABASE IF NOT EXISTS demo.db;

DROP TABLE IF EXISTS demo.db.lifecycle;
CREATE TABLE demo.db.lifecycle (
  id       bigint,
  ts       timestamp,
  customer string,
  amt      double
)
USING iceberg
TBLPROPERTIES ('format-version'='2');

INSERT INTO demo.db.lifecycle VALUES (1, TIMESTAMP'2026-07-01 10:00:00','alice',10.0);
INSERT INTO demo.db.lifecycle VALUES (2, TIMESTAMP'2026-07-01 10:05:00','bob',  20.0);
INSERT INTO demo.db.lifecycle VALUES (3, TIMESTAMP'2026-07-01 10:10:00','carol',30.0);
INSERT INTO demo.db.lifecycle VALUES (4, TIMESTAMP'2026-07-01 10:15:00','dave', 40.0);
INSERT INTO demo.db.lifecycle VALUES (5, TIMESTAMP'2026-07-01 10:20:00','erin', 50.0);
INSERT INTO demo.db.lifecycle VALUES (6, TIMESTAMP'2026-07-01 10:25:00','frank',60.0);
INSERT INTO demo.db.lifecycle VALUES (7, TIMESTAMP'2026-07-01 10:30:00','grace',70.0);
INSERT INTO demo.db.lifecycle VALUES (8, TIMESTAMP'2026-07-01 10:35:00','heidi',80.0);

-- Module 05's ending: one live file, eight replaced ones still on disk.
CALL demo.system.rewrite_data_files(table => 'db.lifecycle');
