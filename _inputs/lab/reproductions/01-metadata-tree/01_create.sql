-- Lab repro #1 — build a tiny, hand-traceable Iceberg table.
-- Two separate INSERTs on purpose: each is its own commit -> its own snapshot + manifest + data file.
-- Partitioned by event_date so the manifest-list carries real partition min/max ranges.

CREATE DATABASE IF NOT EXISTS demo.db;

DROP TABLE IF EXISTS demo.db.events;

CREATE TABLE demo.db.events (
  id        bigint,
  event_date date,
  user      string,
  amt       double
)
USING iceberg
PARTITIONED BY (event_date);

-- Commit #1 (snapshot s1): one partition (06-27) -> one data file
INSERT INTO demo.db.events VALUES
  (1, DATE'2026-06-27', 'alice', 10.0),
  (2, DATE'2026-06-27', 'bob',   20.0);

-- Commit #2 (snapshot s2): a new partition (06-28) -> a new data file; s1's manifest is REUSED
INSERT INTO demo.db.events VALUES
  (3, DATE'2026-06-28', 'alice', 30.0),
  (4, DATE'2026-06-28', 'carol', 40.0);
