-- Repro #14, step 3 — the same table, read by DuckDB, after the rollback.
--
-- Run from the HOST:  duckdb -c ".read 03_duckdb.sql"
--
-- Step 2 left the catalog unambiguous: `main` points at the pre-delete
-- snapshot, and pyiceberg reports the recovered row count. This asks whether a
-- third engine agrees — and then shows what to do when it does not.
--
-- Two reads of one table:
--   the default scan      — whatever the engine resolves on its own
--   pinned to main        — the snapshot the catalog actually calls current
--
-- If those two disagree, the recovery happened for some of your stack and not
-- the rest, and nothing errored to tell you.

INSTALL iceberg;
LOAD iceberg;

CREATE SECRET (
    TYPE s3, KEY_ID 'admin', SECRET 'password',
    ENDPOINT 'localhost:9000', USE_SSL false, URL_STYLE 'path'
);

ATTACH 'warehouse' AS ice (
    TYPE iceberg, ENDPOINT 'http://localhost:8181', AUTHORIZATION_TYPE 'none'
);

-- The snapshot id is substituted by the capture script from the catalog's own
-- `main` ref — it regenerates on every run and must never be hardcoded.
SELECT 'DuckDB, default scan'        AS how, count(*) AS rows FROM ice.db.interop
UNION ALL
SELECT 'DuckDB, pinned to main', count(*) FROM ice.db.interop AT (VERSION => __MAIN_SNAPSHOT__);
