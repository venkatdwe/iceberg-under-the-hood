-- Repro #10, step 5 — a third reader, against the same v3 table.
--
-- Run from the HOST (DuckDB is not in the Spark container):
--   duckdb -c ".read 05_duckdb_v3.sql"
--
-- Layer 4 showed pyiceberg 0.9.1 raising on this table. This is the same table,
-- read by a different engine that shares no code with either Spark or pyiceberg.
--
-- Watch the row count, not just whether it errors. The table holds 500 rows with
-- one deleted. 499 means the deletion vector was APPLIED. 500 would mean the
-- reader saw the data files, ignored the vector, and returned a wrong answer
-- without complaining — which is the worse failure and the one worth testing for.
--
-- AUTHORIZATION_TYPE 'none' is required against this lab; without it DuckDB
-- assumes oauth2 and fails with "no 'secret' was provided".

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

-- One query, one small table. Separate SELECTs print a box each, and the
-- setup statements above print empty "Success" boxes of their own — on a
-- recorded terminal that pushes the only number that matters off the screen.
SELECT 'v2  position deletes'  AS iceberg_table, count(*) AS rows FROM ice.db.dv_v2
UNION ALL
SELECT 'v3  deletion vector',        count(*)              FROM ice.db.dv_v3;
