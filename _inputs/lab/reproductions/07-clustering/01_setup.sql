-- Lab repro #7 — clustering: why the same rows in the same number of files
-- can be fast or slow depending only on WHICH rows share a file.
--
-- Six commits, each carrying a slice of ids but customers from across the whole
-- range — the shape you get from any feed ordered by time rather than by the
-- column people filter on. Nobody arranged this badly; it is just what arrival
-- order looks like.
--
-- Unpartitioned on purpose: partitioning is Module 04's subject, and adding it
-- here would let a viewer credit the partition rather than the clustering.
--
-- write.distribution-mode = none is load-bearing. Spark's default shuffles rows
-- before writing, which pre-sorts each batch and hides the very problem this
-- repro exists to show. `none` writes what it is given, in the order given.
--
-- customer_id and amt are deliberately INDEPENDENT of each other and of id
-- (different prime multipliers, mod 1000), so clustering one column tells you
-- nothing about the other. An earlier draft used amt = id, which made the two
-- columns perfectly correlated and produced a misleading z-order result.

CREATE DATABASE IF NOT EXISTS demo.db;

DROP TABLE IF EXISTS demo.db.clustering;
CREATE TABLE demo.db.clustering (
  id          bigint,
  customer_id int,
  amt         double
)
USING iceberg
TBLPROPERTIES (
  'format-version'='2',
  'write.distribution-mode'='none'
);
