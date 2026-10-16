-- Lab repro #4 — evolve a live table's schema AND its partitioning, then prove
-- nothing was rewritten.
--
-- The claim Module 03's recap makes is "Iceberg renames a column or re-partitions
-- a live table without rewriting a byte. Field IDs are the trick." This builds the
-- table that lets us check that, physically.
--
-- Deliberately partitioned by days(event_ts) with NO separate date column: that is
-- hidden partitioning. The reader filters `event_ts`, and Iceberg maps the filter
-- onto the partition itself — nothing to remember, nothing to keep in sync.

CREATE DATABASE IF NOT EXISTS demo.db;

DROP TABLE IF EXISTS demo.db.evolve;
CREATE TABLE demo.db.evolve (
  id        bigint,
  event_ts  timestamp,
  user_name string,
  amt       double
)
USING iceberg
PARTITIONED BY (days(event_ts))
TBLPROPERTIES ('format-version'='2');

-- ── BEFORE any evolution: 6 rows over 3 days = 3 data files, one per day ──
INSERT INTO demo.db.evolve VALUES
  (1, TIMESTAMP'2026-07-01 09:00:00', 'alice', 10.0),
  (2, TIMESTAMP'2026-07-01 17:30:00', 'bob',   20.0),
  (3, TIMESTAMP'2026-07-02 08:15:00', 'carol', 30.0),
  (4, TIMESTAMP'2026-07-02 21:45:00', 'dave',  40.0),
  (5, TIMESTAMP'2026-07-03 11:05:00', 'erin',  50.0),
  (6, TIMESTAMP'2026-07-03 19:20:00', 'frank', 60.0);

-- ── EVOLUTION 1 — rename a column ────────────────────────────────────────
-- The interesting part is what does NOT happen: no data file is touched, and
-- no snapshot is created. Only a new schema is written into metadata.json,
-- reusing the same field IDs.
ALTER TABLE demo.db.evolve RENAME COLUMN user_name TO customer;

-- ── EVOLUTION 2 — add a column ───────────────────────────────────────────
-- Gets a BRAND NEW field id (5). The 6 rows already on disk have no column
-- with that id, so a reader fills NULL — again without rewriting them.
ALTER TABLE demo.db.evolve ADD COLUMN region string;

-- ── EVOLUTION 3 — change how the table is partitioned ────────────────────
-- The existing files stay under the OLD spec. Only new writes use the new one,
-- so a re-partition costs nothing up front and both layouts serve one table.
ALTER TABLE demo.db.evolve ADD PARTITION FIELD bucket(4, id);

-- ── AFTER evolution: 2 more rows, written under the new spec + new schema ──
INSERT INTO demo.db.evolve VALUES
  (7, TIMESTAMP'2026-07-04 10:00:00', 'grace', 70.0, 'emea'),
  (8, TIMESTAMP'2026-07-04 14:00:00', 'heidi', 80.0, 'apac');
