-- Repro #10, step 5 — what `_last_updated_sequence_number` actually tells you.
--
-- Run: docker exec spark-iceberg spark-sql -f /tmp/10_sequence.sql
--
-- Row lineage gives every row a `_last_updated_sequence_number`, and the
-- obvious reading is "this row changed in that commit". Measure it and the
-- reading does not hold: the sequence number moves for every row in any FILE
-- the commit rewrote, not for the rows the statement named.
--
-- The table is deliberately spread across several files and left unsorted, so
-- a 3-row UPDATE touches one file and leaves the others alone. That is what
-- makes the gap between "rows updated" and "rows reporting the new number"
-- visible at all -- on a single-file table both numbers would be the row count
-- and there would be nothing to see.
--
-- Touches only db.seq_demo. Module 10's other scripts own dv_v2, dv_v3,
-- dv_upgrade and lineage_demo.

CREATE DATABASE IF NOT EXISTS demo.db;

DROP TABLE IF EXISTS demo.db.seq_demo;
CREATE TABLE demo.db.seq_demo (id bigint, val string)
USING iceberg
TBLPROPERTIES ('format-version'='3',
               'write.delete.mode'='merge-on-read',
               'write.distribution-mode'='none');

INSERT INTO demo.db.seq_demo SELECT id, repeat('x', 40) FROM range(1, 201);

-- How many files the 200 rows landed in. The UPDATE below rewrites exactly one
-- of them, so this count is the denominator for everything that follows.
SELECT 'data files' AS what, count(DISTINCT _file) AS n FROM demo.db.seq_demo;

-- One commit so far, so every row reports sequence 1.
SELECT 'BEFORE UPDATE' AS phase,
       _last_updated_sequence_number AS seq,
       count(*)                      AS rows
FROM demo.db.seq_demo GROUP BY 2 ORDER BY 2;

UPDATE demo.db.seq_demo SET val = 'updated' WHERE id <= 3;

-- Three rows were named. Count how many report the new sequence number.
SELECT 'AFTER UPDATE' AS phase,
       _last_updated_sequence_number AS seq,
       count(*)                      AS rows
FROM demo.db.seq_demo GROUP BY 2 ORDER BY 2;

-- Expect one whole file's worth at sequence 2, not 3. The update rewrote the
-- file copy-on-write and the sequence number moved for every row in it, so the
-- field tells you "something in this file changed", not "this row changed".
