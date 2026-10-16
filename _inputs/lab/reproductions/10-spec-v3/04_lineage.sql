-- Repro #10, step 4 — row lineage: allocated in metadata, not usable as an identity.
--
-- Run: docker exec spark-iceberg spark-sql -f /tmp/10_lineage.sql
--
-- Row lineage is the feature most often cited when arguing for spec v3: every
-- row gets a stable id that survives being rewritten, so you can finally track
-- a row across compaction. This measures whether you can actually use it.
--
-- The tell is the DISTINCT count against the data-file count. Iceberg derives a
-- row's id from its file's first_row_id PLUS the row's position in that file.
-- If the read path returns only the file-level value, then every row in a file
-- reads back identical — and distinct_ids will equal the number of files.
--
-- Deliberately no updates and no deletes: this is a plain table that has done
-- nothing but exist, so nothing else can be blamed for the result.

DROP TABLE IF EXISTS demo.db.lineage_demo;

CREATE TABLE demo.db.lineage_demo (id bigint, val string)
USING iceberg
TBLPROPERTIES ('format-version'='3',
               'write.distribution-mode'='none');

INSERT INTO demo.db.lineage_demo SELECT id, repeat('x', 40) FROM range(1, 201);

-- 200 rows. If _row_id were a row identity, distinct_ids would be 200.
SELECT 'BEFORE COMPACTION' AS phase,
       count(*)                  AS rows,
       count(DISTINCT _row_id)   AS distinct_ids,
       min(_row_id)              AS lowest,
       max(_row_id)              AS highest
FROM demo.db.lineage_demo;

-- The sequence number, by contrast, behaves exactly as specified.
SELECT 'sequence numbers'        AS phase,
       count(DISTINCT _last_updated_sequence_number) AS distinct_seq
FROM demo.db.lineage_demo;

CALL demo.system.rewrite_data_files(
  table   => 'db.lineage_demo',
  options => map('rewrite-all', 'true')
);

-- One file now. If the ids track rows, this is unchanged at 200 distinct.
SELECT 'AFTER COMPACTION' AS phase,
       count(*)                  AS rows,
       count(DISTINCT _row_id)   AS distinct_ids,
       min(_row_id)              AS lowest,
       max(_row_id)              AS highest
FROM demo.db.lineage_demo;
