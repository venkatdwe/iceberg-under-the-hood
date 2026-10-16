-- Lab repro #3 — delete the SAME row under two strategies and watch what each writes.
-- Two identical tables; only the write.delete.mode differs.

CREATE DATABASE IF NOT EXISTS demo.db;

-- ── COPY-ON-WRITE: a delete REWRITES the whole data file ──────────────────
DROP TABLE IF EXISTS demo.db.events_cow;
CREATE TABLE demo.db.events_cow (id bigint, event_date date, user string, amt double)
USING iceberg PARTITIONED BY (event_date)
TBLPROPERTIES ('write.delete.mode'='copy-on-write', 'format-version'='2');

INSERT INTO demo.db.events_cow VALUES
  (1, DATE'2026-07-01', 'alice', 10.0),
  (2, DATE'2026-07-01', 'bob',   20.0),
  (3, DATE'2026-07-01', 'carol', 30.0);

DELETE FROM demo.db.events_cow WHERE user = 'bob';

-- ── MERGE-ON-READ: a delete writes a small TOMBSTONE, data file untouched ──
DROP TABLE IF EXISTS demo.db.events_mor;
CREATE TABLE demo.db.events_mor (id bigint, event_date date, user string, amt double)
USING iceberg PARTITIONED BY (event_date)
TBLPROPERTIES ('write.delete.mode'='merge-on-read', 'format-version'='2');

INSERT INTO demo.db.events_mor VALUES
  (1, DATE'2026-07-01', 'alice', 10.0),
  (2, DATE'2026-07-01', 'bob',   20.0),
  (3, DATE'2026-07-01', 'carol', 30.0);

DELETE FROM demo.db.events_mor WHERE user = 'bob';
