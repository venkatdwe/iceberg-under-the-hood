-- Repro #7, step 2 — rewrite the SAME rows clustered by customer_id.
--
-- strategy => 'sort' orders rows as it rewrites them; bin-pack (Module 05)
-- only changes how many files hold them. Same procedure, same commit
-- protocol — the difference is entirely in what ends up next to what.
--
-- rewrite-all is set because these files are already near the target size, so
-- the default cost-based check would decline. target-file-size-bytes is small
-- (8 KB) so the 6,000 rows land in several files rather than one; with a
-- single output file there is nothing to skip and nothing to measure.

CALL demo.system.rewrite_data_files(
  table       => 'db.clustering',
  strategy    => 'sort',
  sort_order  => 'customer_id ASC NULLS LAST',
  options     => map('min-input-files','1','rewrite-all','true',
                     'target-file-size-bytes','8192')
);
