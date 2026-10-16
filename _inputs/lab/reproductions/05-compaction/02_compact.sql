-- Repro #5, step 2 — compact.
--
-- rewrite_data_files is a stored procedure, not DDL: it reads the current
-- files, writes replacements, and commits the swap through the same protocol
-- as any other write (Module 02). Defaults apply here — bin-pack strategy,
-- 512 MB target file size, and a minimum of 5 input files before it bothers.
-- Our 8 one-row files clear that minimum and fit a single output file with
-- room to spare.
--
-- Returns: rewritten_data_files_count, added_data_files_count,
--          rewritten_bytes, failed_data_files_count

CALL demo.system.rewrite_data_files(table => 'db.trickle');
