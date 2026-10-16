-- Repro #8, step 2 — delete the same rows from both tables.
--
-- One row from the copy-on-write table: enough to show that the unit of
-- rewrite is a FILE, not a row.
--
-- Three rows from the merge-on-read table, one per commit, because read
-- amplification is about delete files ACCUMULATING — a single tombstone tells
-- you nothing about the trend.

DELETE FROM demo.db.gov_cow WHERE id = 2500;

DELETE FROM demo.db.gov_mor WHERE id = 2500;
DELETE FROM demo.db.gov_mor WHERE id = 1500;
DELETE FROM demo.db.gov_mor WHERE id = 3500;
