# Module 10 findings — measured 2026-09-03

Probe run to decide whether module 10 (Spec v3: deletion vectors, row lineage)
could be lab-backed or had to be conceptual. **It can be lab-backed**, and the
result is stronger than expected.

## Spec v3 is writable in this lab

Iceberg 1.9.0 / Spark 3.5.6 creates format-version 3 tables with no extra
configuration:

```sql
CREATE TABLE demo.db.v3dv (id bigint, val string) USING iceberg
TBLPROPERTIES ('format-version'='3', 'write.delete.mode'='merge-on-read');
```

`t.metadata.format_version` reads back as `3`.

**`write.delete.mode` is load-bearing.** A first probe created a v3 table without
it, deleted a row, and produced **zero delete files** — the default is still
copy-on-write, so the whole data file was rewritten and no deletion vector
appeared. A v3 table alone does not give you deletion vectors; v3 *plus*
merge-on-read does. That is a trap worth teaching, because "we upgraded to v3"
is exactly what a team would say before measuring nothing had changed.

## The headline: 42 bytes to delete a row

500 rows, 50-byte payload, one row deleted, merge-on-read:

```
format-version        3
operation             delete
total-delete-files    1
total-position-deletes 1
added-files-size      42        <- bytes written for the delete
total-data-files      6
rows readable         (see below — pyiceberg cannot complete the scan)
```

**42 bytes.** And the like-for-like comparison is now measured. `db.v2dv` and
`db.v3dv` are identical — 500 rows, 50-byte payload, merge-on-read, same single
row deleted — and differ only in format-version:

| | bytes written | delete files | position deletes | pyiceberg 0.9.1 read |
|---|---|---|---|---|
| **v2** | **1,412** | 1 | 1 | OK — 499 rows |
| **v3** | **42** | 1 | 1 | **ValueError: 'PUFFIN' is not a valid FileFormat** |

**33.6x smaller**, for the identical row on an identical table. Both record one
delete file and one position delete; the difference is entirely in what that
file *is* — a position-delete parquet versus a Puffin deletion vector.

Note the second column of that table is the real story: the reader that handles
v2 fine cannot open the v3 result at all.

## The better headline: your client cannot read it

Reading that table back through pyiceberg 0.9.1 raises:

```
ValueError: 'PUFFIN' is not a valid FileFormat
```

The deletion vector is a Puffin file, and pyiceberg 0.9.1's `FileFormat` enum
does not contain `PUFFIN`. Spark writes it happily; the Python client in the
same container cannot complete a scan of the result.

This is the real production risk of adopting v3, and it is not the one people
discuss. The concept is simple and the write path works. What bites is
**ecosystem lag** — the engine that writes and the client that reads are
versioned separately, and v3 tables are readable only by the subset of your
stack that has caught up. A table that one tool writes and another cannot open
is a worse outcome than not adopting yet.

It also connects straight to module 14: the course now has two independent,
measured cases of engines disagreeing about the same table — this one, and
DuckDB resolving the latest snapshot instead of the branch ref after a rollback.

## Still to measure before this ships

1. **Root-cause the `_row_id` read path** before narrating it. Confirmed:
   distinct ids == file count. NOT confirmed: whether the positional offset is
   missing in Spark's metadata-column resolution or in the Iceberg library.
   The module should describe observed behaviour, not name a culprit.
1. ~~Whether DuckDB 1.5.2 can read the v3 table.~~ **ANSWERED 2026-09-08: it
   can, and correctly.** 499 rows — the deletion vector was applied, not
   ignored (ignoring it would return 500 and be silently wrong). So the lesson
   sharpened exactly as hoped and then some: support is per-client and does NOT
   follow seniority. Iceberg's own reference Python library fails where a
   third-party analytical engine succeeds. Not inferable from a version number;
   test the clients you actually run.
4. **Variant type** — not probed. Likely not in 1.9.0; confirm rather than
   assume.
5. Re-read the v3 table with Spark itself to confirm the delete is applied
   (2 of 3 rows on the first probe suggests yes, but confirm on `db.v3dv`).

## Lab tables created by this probe

`db.v3probe` (v3, copy-on-write default) and `db.v3dv` (v3, merge-on-read).
Both are module 10's own and touch nothing else. `db.v2dv` is the comparison
table.
