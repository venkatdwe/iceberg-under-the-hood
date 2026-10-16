-- Repro #10, step 2 — delete the same row from both tables.
--
-- ONE row, from each. That is enough: the point is what the delete WRITES, not
-- how much of it there is. A single row keeps the byte figures small enough to
-- read on screen and makes the v2/v3 ratio the only thing that moves.
--
-- Both tables are merge-on-read (see 01_setup.sql), so both produce a delete
-- file rather than rewriting data. The difference is what KIND of delete file:
-- a position-delete parquet on v2, a Puffin deletion vector on v3.

DELETE FROM demo.db.dv_v2 WHERE id = 250;

DELETE FROM demo.db.dv_v3 WHERE id = 250;
