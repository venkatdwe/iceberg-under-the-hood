-- Repro #11, step 2 — a second engine, over the same contract.
--
-- Run from the HOST (DuckDB is not in the Spark container):
--   duckdb -init /dev/null -c ".read 02_duckdb.sql"
--
-- Every table this reads was written by Spark. DuckDB has never seen Spark's
-- configuration, shares no library with it, and holds no reference to the
-- warehouse layout. It knows one URL and the REST spec, and that is enough.
--
-- This is the payoff of Layer 1: the catalog is the contract, so "which engine
-- wrote it" stops being a question anyone has to ask.
--
-- AUTHORIZATION_TYPE 'none' is required against this lab. Without it DuckDB
-- assumes oauth2 and fails with "no 'secret' was provided" — the single most
-- likely thing to block someone reproducing this.
--
-- The S3 credentials are passed by hand because this catalog vends none
-- (Layer 4). That is the thing credential vending would remove.

INSTALL iceberg;
LOAD iceberg;

CREATE SECRET (
    TYPE s3,
    KEY_ID 'admin',
    SECRET 'password',
    ENDPOINT 'localhost:9000',
    USE_SSL false,
    URL_STYLE 'path'
);

ATTACH 'warehouse' AS ice (
    TYPE iceberg,
    ENDPOINT 'http://localhost:8181',
    AUTHORIZATION_TYPE 'none'
);

SELECT '=== LAYER 5: A SECOND ENGINE, SAME CATALOG ===' AS layer;

-- Every one of these was created by Spark.
SELECT database, schema, name FROM (SHOW ALL TABLES) ORDER BY name;

-- Reads THIS module's table, created by 00_setup.sql. Earlier drafts read
-- another module's table and broke when the lab was rebuilt: the catalog still
-- lists those names but loadTable 404s on them.
--
-- Deliberately not db.concurrent either. That table has been rolled back, and
-- DuckDB 1.5.2 resolves the latest snapshot rather than the branch ref, so it
-- reports the pre-rollback state. That divergence is module 14's headline
-- (reproductions/14-interop/FINDINGS.md); showing it here would contradict
-- module 09 on screen with no explanation and spoil the capstone.
SELECT '--- a table Spark wrote, read by DuckDB ---' AS layer;
SELECT region, count(*) AS rows
FROM ice.db.catalog_demo
GROUP BY region
ORDER BY region;
