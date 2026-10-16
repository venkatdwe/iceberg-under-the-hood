-- Repro #7, step 3 — rewrite the same rows again, z-ordered on both columns.
--
-- Z-ordering interleaves the bits of several columns so that rows close in
-- ANY of those dimensions tend to land together — the usual answer when two
-- different filters both matter.
--
-- Measure the result rather than assuming it: on this data it does not split
-- the difference the way the description implies. See the README.

CALL demo.system.rewrite_data_files(
  table       => 'db.clustering',
  strategy    => 'sort',
  sort_order  => 'zorder(customer_id, amt)',
  options     => map('min-input-files','1','rewrite-all','true',
                     'target-file-size-bytes','8192')
);
