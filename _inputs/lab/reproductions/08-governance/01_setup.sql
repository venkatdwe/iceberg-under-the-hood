-- Lab repro #8 — what a single deleted row actually costs, both ways.
--
-- Module 03 established that copy-on-write rewrites files and merge-on-read
-- writes tombstones. This puts a price on that choice: bytes written per byte
-- of real change (write amplification), and files a reader must merge
-- afterwards (read amplification).
--
-- Two tables identical but for write.delete.mode, so the only variable is the
-- strategy. 5,000 rows with a 200-byte payload, so the files are large enough
-- that rewriting one is visibly expensive.
--
-- write.distribution-mode = none keeps Spark from reshuffling on write, so the
-- file layout stays predictable between runs.

CREATE DATABASE IF NOT EXISTS demo.db;

DROP TABLE IF EXISTS demo.db.gov_cow;
CREATE TABLE demo.db.gov_cow (id bigint, customer_id int, payload string)
USING iceberg
TBLPROPERTIES ('format-version'='2',
               'write.delete.mode'='copy-on-write',
               'write.distribution-mode'='none');

DROP TABLE IF EXISTS demo.db.gov_mor;
CREATE TABLE demo.db.gov_mor (id bigint, customer_id int, payload string)
USING iceberg
TBLPROPERTIES ('format-version'='2',
               'write.delete.mode'='merge-on-read',
               'write.distribution-mode'='none');

INSERT INTO demo.db.gov_cow
  SELECT id, CAST(pmod(id * 7919, 1000) AS int), repeat('x', 200) FROM range(1, 5001);
INSERT INTO demo.db.gov_mor
  SELECT id, CAST(pmod(id * 7919, 1000) AS int), repeat('x', 200) FROM range(1, 5001);
