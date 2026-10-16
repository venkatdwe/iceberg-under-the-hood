-- Repro #6, step 3 — compact the manifests themselves.
--
-- Data files are not the only thing that accumulates. Every commit writes a
-- manifest, so a table with a long commit history carries a long manifest
-- list, and the planner reads that list on every query before it opens any
-- data at all. rewrite_manifests repacks them.
--
-- Returns: rewritten_manifests_count, added_manifests_count

CALL demo.system.rewrite_manifests(table => 'db.lifecycle');
