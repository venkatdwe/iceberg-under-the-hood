-- Repro #6, step 4 — turn on the metadata cleanup that is off by default.
--
-- Layer 5 shows a table with 2 snapshots carrying 11 metadata.json versions.
-- Nothing so far has touched them: expire_snapshots prunes snapshots and the
-- data they reference, not the metadata trail.
--
-- These two properties are the mechanism, and the first one defaults to FALSE,
-- which is why most tables accumulate this quietly forever. Cleanup happens on
-- the NEXT commit, not retroactively — so the INSERT is what triggers it.

ALTER TABLE demo.db.lifecycle SET TBLPROPERTIES (
  'write.metadata.delete-after-commit.enabled' = 'true',
  'write.metadata.previous-versions-max'       = '3'
);

INSERT INTO demo.db.lifecycle VALUES (99, TIMESTAMP'2026-07-02 09:00:00','ivan',90.0);
