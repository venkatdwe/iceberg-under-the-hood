# Apache Iceberg — Under the Hood

The lab for a 15-module course that opens the files. Every claim in the videos
is measured here, by a script in this repo that you can run yourself.

> Everyone explains the API. We open the files.

## Start here — two commands

```bash
just lab-up        # Spark + REST catalog + MinIO, via docker compose
just m00-why       # the one demo that explains why Iceberg exists
```

The first `lab-up` does two one-time downloads: it clones the lab stack
([tabular-io/docker-spark-iceberg](https://github.com/tabular-io/docker-spark-iceberg),
a couple of seconds) and then pulls the Docker images — **about 2.8 GB over the
wire, 4.9 GB once unpacked on disk**, most of it `tabulario/spark-iceberg`.
Every run after that is instant. The stack is not vendored here because it is
somebody else's, so it is fetched rather than shipped.

`m00-why` does the same thing to a directory of Parquet files and to an Iceberg
table — it adds one file — and prints what each does about it:

```
=== HIVE-STYLE: the directory IS the table ===
  rows in table      300
  ...one file appears in the directory...
  rows in table      351   <- grew by 51, with no commit

=== ICEBERG: the metadata IS the table ===
  rows in table      300
  ...the same file trick, into the table's own data directory...
  rows in table      300   <- UNCHANGED
```

That is the entire argument for a table format, in two numbers.

## Prerequisites

- **Docker Desktop** — runs the lab (Spark, Iceberg REST catalog, MinIO)
- **`just`** — the task runner: `brew install just`
- **DuckDB** *(optional)* — only for the `*-duckdb` recipes, which run on the host
- **~6 GB free disk** — 4.9 GB of images plus the warehouse the labs write

Nothing else is installed on your machine. Everything else lives in containers.

## Running a module's lab

Every module with a lab has a recipe named after it. `just` on its own lists
them all with what each one measures:

```bash
just                # list every recipe
just m01-walk       # walk the metadata tree by hand
just m03-deletes    # delete one row under CoW and under MoR, compare
just m07-cluster    # scattered vs sorted vs z-ordered, files opened per lookup
just m10-spec       # one row deleted from a v2 and a v3 table: 1,416 bytes vs 42
```

Output lands in your terminal, not in a notebook. That is deliberate — you
should be able to see the numbers change when you change the inputs.

## Changing the inputs

The scripts each recipe runs are plain files under
`_inputs/lab/reproductions/<module>/`. Every recipe reads its script fresh on
each run — the Spark ones copy it into the container, the two DuckDB ones run it
straight from the repo — so an edit takes effect the next time you run it. There
is nothing to rebuild:

```bash
$EDITOR _inputs/lab/reproductions/05-compaction/01_setup.sql   # write 16 files, not 8
just m05-compact                                               # same recipe, your numbers
```

For a free hand against the same warehouse:

```bash
just sql            # interactive spark-sql prompt
just shell          # bash inside the spark-iceberg container
just reset          # rebuild demo.db.events, the module 01 table
```

Changing a script will of course move the numbers away from the ones quoted in
the videos. `git checkout _inputs/lab/reproductions/` restores the scripts; each
module's own recipe rebuilds its table from scratch, so re-running it is enough
to get the quoted numbers back.

## The modules

<!-- modules:begin -->

| # | Module | | Length |
|---|---|---|---|
| 00 | Welcome & Why Iceberg | ★ | 13:26 |
| 01 | The Metadata Tree | ★★ | 11:32 |
| 02 | How a Write Commits — ACID & the Catalog | ★★ | 7:15 |
| 03 | Reads, Deletes & the Two Strategies — CoW vs MoR | ★★ | 9:15 |
| 04 | Schema & Partition Evolution | ★★ | 11:57 |
| 05 | The Small-File Problem & Compaction | ★★ | 11:57 |
| 06 | Snapshot & Metadata Lifecycle | ★★ | 13:29 |
| 07 | Partitioning, Clustering & Data Skipping in Practice | ★★★ | 13:28 |
| 08 | Cost & Performance Governance | ★★★ | 13:04 |
| 09 | Concurrency, Recovery & Maintenance Automation | ★★★ | 11:34 |
| 10 | Frontier — Spec v3: Deletion Vectors & Row Lineage | ★★★ | 14:21 |
| 11 | Catalogs & the REST Spec — The Interop Pivot | ★★ | 12:03 |
| 12 | Iceberg vs Delta vs Hudi — A Neutral Decision Framework | ★★ | 13:38 |
| 13 | Iceberg on Snowflake & Databricks | ★★ | 14:16 |
| 14 | Interop Capstone — One Table, Every Engine | ★★★ | 13:25 |

Total 3h 4m, measured from the rendered videos at 1.10× playback.

<!-- modules:end -->

Modules 12 and 13 have no lab: there is no Delta, Hudi, Snowflake or Databricks
engine here, and the course does not pretend otherwise. They compare
architecture against each project's published specification instead.

## Where things live

```
_inputs/lab/reproductions/   one directory per module — the scripts the videos run
  00-why-iceberg/            README.md in each explains what it measures and why
  01-metadata-tree/
  ...
_inputs/repos/               the docker-spark-iceberg stack (fetched, gitignored)
scripts/reconcile_catalog.sh runs from `lab-up`; see Troubleshooting
Justfile                     every lab recipe
```

Each reproduction directory has its own `README.md` with the measured numbers,
the gotchas found while building it, and what could not be demonstrated.

## Troubleshooting

**`just lab-up` succeeded but a table 404s.** Bringing the lab up can reset
MinIO's warehouse while the REST catalog keeps its entries, so tables are listed
but their metadata is gone — and because the repro scripts silence their own
stderr, the symptom is blank numbers rather than an error. `lab-up` now clears
those entries for you (`scripts/reconcile_catalog.sh`), and each module's recipe
recreates its own table. To do it by hand for one table:

```bash
curl -X DELETE "http://localhost:8181/v1/namespaces/db/tables/<name>?purgeRequested=false"
```

`DROP TABLE IF EXISTS` will not help: it loads the table first, and the load is
what fails.

**DuckDB says "no 'secret' was provided".** The `ATTACH` needs
`AUTHORIZATION_TYPE 'none'` against this lab — without it DuckDB assumes oauth2.
It is the single most common thing to trip over.

**Byte counts differ slightly from the video.** Expected. Parquet and Avro
writers are not byte-for-byte deterministic; file counts, row counts and skip
percentages are stable, absolute byte sizes drift by a few bytes per run.

**Docker says it cannot connect.** Docker Desktop itself is not running —
`open -a Docker` on macOS, then wait for the whale to settle before `just lab-up`.

## Credentials

The lab's MinIO uses `admin` / `password`, the documented defaults of the
upstream compose stack. They appear in the scripts because they are what the
local containers expect. Nothing here reaches anything outside your machine.
