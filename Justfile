# Apache Iceberg — Under the Hood: hands-on lab runner.
# You run these; output lands in YOUR terminal. One-time setup: `brew install just`.
# List recipes:  just            (or  just --list)

lab_dir := "_inputs/repos/docker-spark-iceberg"
repro   := "_inputs/lab/reproductions"
compose_files := "-f docker-compose.yml -f ../../../compose.override.yml"
filter  := "grep -viE 'WARNING|FutureWarning|warnings.warn|DeprecationWarning|PYTHON_VERSION|SLF4J|log4j'"

# show all recipes
default:
    @just --list

# ── lab lifecycle ─────────────────────────────────────────────────────────
# The compose stack is a third-party repo, gitignored (_inputs/repos/*/), so a
# fresh clone of THIS repo does not have it and `lab-up` used to fail on `cd`
# with no explanation. The README promises two commands; this makes that true.
# clone the lab stack (third-party, gitignored) if it is not here yet
lab-fetch:
    @test -d {{lab_dir}} || (echo "fetching the lab stack (one time)…" && \
        git clone --depth 1 https://github.com/tabular-io/docker-spark-iceberg {{lab_dir}})

# fetch everything without starting anything (good before travelling)
# Only the three registry images are pulled; the Spark one is built from
# upstream's spark/Dockerfile -- see compose.override.yml for why.
lab-pull: lab-fetch
    cd {{lab_dir}} && docker compose {{compose_files}} pull rest minio mc
    cd {{lab_dir}} && docker compose {{compose_files}} build spark-iceberg

# bring the stack up (Spark + REST catalog + MinIO)
# First run pulls three images and BUILDS the Spark one (several minutes,
# once) so the lab runs Iceberg 1.9.0 rather than the frozen published
# image's 1.8.1 -- compose.override.yml records what that breaks.
lab-up: lab-fetch
    cd {{lab_dir}} && docker compose {{compose_files}} up -d
    @# Coming up can reset the warehouse while the catalog keeps its entries,
    @# which leaves every affected lab printing blank numbers instead of failing.
    @scripts/reconcile_catalog.sh

# tear the stack down
lab-down:
    cd {{lab_dir}} && docker compose {{compose_files}} down

# container status
lab-ps:
    @docker ps --filter name=spark-iceberg --filter name=iceberg-rest --filter name=minio --filter name=mc --format "table {{{{.Names}}\t{{{{.Status}}"
    @# Four braces is just's escape for a literal double brace; the closing
    @# pair needs none. The extra pair printed a stray suffix on every row.

# ── Module 01 — the metadata tree ─────────────────────────────────────────
# (re)build the clean 4-row baseline table
reset:
    docker cp {{repro}}/01-metadata-tree/01_create.sql spark-iceberg:/tmp/01_create.sql
    docker exec spark-iceberg spark-sql -f /tmp/01_create.sql

# list what is physically in object storage under db.events
# NOTE this is the PREFIX, not the table. DROP TABLE leaves object storage
# untouched, so re-running a repro accumulates the files of every past
# incarnation here -- measured 34 data files in a prefix whose live table
# references 2. `just meta` resolves the catalog pointer; this does not.
files:
    docker exec mc mc ls -r minio/warehouse/db/events/

# pretty-print the newest metadata.json
meta:
    #!/usr/bin/env bash
    set -euo pipefail
    # Ask the CATALOG which metadata.json is current, rather than taking the
    # highest-numbered file in the prefix. DROP TABLE does not purge object
    # storage, so this prefix accumulates every past incarnation of the table:
    # measured 42 metadata.json files from 11 dead tables, where sorting by
    # name picked a fossil with the wrong snapshot count AND an engine version
    # from before the image was rebuilt. The catalog pointer IS the table --
    # which is the lesson of Module 01, so the helper should not contradict it.
    loc=$(curl -sf http://localhost:8181/v1/namespaces/db/tables/events \
      | python3 -c "import json,sys; print(json.load(sys.stdin)['metadata-location'])")
    f=${loc##*/}
    echo "# current metadata.json (per the catalog pointer): $f"
    docker exec mc mc cat "minio/warehouse/db/events/metadata/$f" | python3 -m json.tool

# REPRO #1 — walk the tree: snapshots → manifest list → manifests → files
m01-walk: reset
    docker cp {{repro}}/01-metadata-tree/03_walk.py spark-iceberg:/tmp/03_walk.py
    @docker exec spark-iceberg python3 /tmp/03_walk.py 2>&1 | {{filter}}

# Module 01 · dump every metadata table with all columns (read-only)
m01-inspect:
    docker cp {{repro}}/01-metadata-tree/04_inspect.py spark-iceberg:/tmp/04_inspect.py
    @docker exec spark-iceberg python3 /tmp/04_inspect.py 2>&1 | {{filter}}

# ── Module 02 — the commit protocol ───────────────────────────────────────
# REPRO #2 — the commit move, a compare-and-swap conflict, and the retry
m02-commit: reset
    docker cp {{repro}}/02-commit-protocol/01_commit.py spark-iceberg:/tmp/02_commit.py
    @docker exec spark-iceberg python3 /tmp/02_commit.py 2>&1 | {{filter}}

# ── Module 03 — CoW vs MoR ────────────────────────────────────────────────
# REPRO #3 — delete the same row under copy-on-write vs merge-on-read; compare what each wrote
m03-deletes:
    docker cp {{repro}}/03-cow-vs-mor/01_setup.sql spark-iceberg:/tmp/03_setup.sql
    docker exec spark-iceberg spark-sql -f /tmp/03_setup.sql >/dev/null 2>&1
    docker cp {{repro}}/03-cow-vs-mor/02_compare.py spark-iceberg:/tmp/03_compare.py
    @docker exec spark-iceberg python3 /tmp/03_compare.py 2>&1 | {{filter}}

# REPRO #4 — rename/reorder/add columns and prove nothing was rewritten
m04-evolve:
    docker cp {{repro}}/04-schema-evolution/01_setup.sql spark-iceberg:/tmp/04_setup.sql
    docker exec spark-iceberg spark-sql -f /tmp/04_setup.sql >/dev/null 2>&1
    docker cp {{repro}}/04-schema-evolution/02_evolve.py spark-iceberg:/tmp/04_evolve.py
    @docker exec spark-iceberg python3 /tmp/04_evolve.py 2>&1 | {{filter}}

# REPRO #5 — compact a small-file table and price what the overhead cost
m05-compact:
    docker cp {{repro}}/05-compaction/01_setup.sql spark-iceberg:/tmp/05_setup.sql
    docker exec spark-iceberg spark-sql -f /tmp/05_setup.sql >/dev/null 2>&1
    docker cp {{repro}}/05-compaction/02_compact.sql spark-iceberg:/tmp/05_compact.sql
    @docker exec spark-iceberg spark-sql -f /tmp/05_compact.sql 2>&1 | {{filter}} | tail -3
    docker cp {{repro}}/05-compaction/03_measure.py spark-iceberg:/tmp/05_measure.py
    @docker exec spark-iceberg python3 /tmp/05_measure.py 2>&1 | {{filter}}

# REPRO #6 — expire snapshots: what is reclaimed, and what history it costs
m06-expire:
    docker cp {{repro}}/06-lifecycle/01_setup.sql spark-iceberg:/tmp/06_setup.sql
    docker exec spark-iceberg spark-sql -f /tmp/06_setup.sql >/dev/null 2>&1
    docker cp {{repro}}/06-lifecycle/02_expire.sql spark-iceberg:/tmp/06_expire.sql
    @docker exec spark-iceberg spark-sql -f /tmp/06_expire.sql 2>&1 | {{filter}} | tail -2
    docker cp {{repro}}/06-lifecycle/03_manifests.sql spark-iceberg:/tmp/06_manifests.sql
    @docker exec spark-iceberg spark-sql -f /tmp/06_manifests.sql 2>&1 | {{filter}} | tail -2
    docker cp {{repro}}/06-lifecycle/04_measure.py spark-iceberg:/tmp/06_measure.py
    @docker exec spark-iceberg python3 /tmp/06_measure.py 2>&1 | {{filter}}
    docker cp {{repro}}/06-lifecycle/05_metadata_cleanup.sql spark-iceberg:/tmp/06_meta.sql
    docker exec spark-iceberg spark-sql -f /tmp/06_meta.sql >/dev/null 2>&1
    @echo "" && echo "===== after enabling metadata cleanup + one commit =====" && docker exec spark-iceberg python3 /tmp/06_measure.py 2>&1 | {{filter}} | sed -n '/LAYER 5/,$p'

# REPRO #7 — scattered vs sorted vs z-ordered: files opened per lookup
m07-cluster:
    docker cp {{repro}}/07-clustering/01_setup.sql spark-iceberg:/tmp/07_setup.sql
    docker exec spark-iceberg spark-sql -f /tmp/07_setup.sql >/dev/null 2>&1
    docker cp {{repro}}/07-clustering/02_load.py spark-iceberg:/tmp/07_load.py
    @docker exec spark-iceberg python3 /tmp/07_load.py 2>&1 | {{filter}} | tail -1
    docker cp {{repro}}/07-clustering/05_measure.py spark-iceberg:/tmp/07_measure.py
    @docker exec spark-iceberg python3 /tmp/07_measure.py "scattered (arrival order)" 2>&1 | {{filter}}
    docker cp {{repro}}/07-clustering/03_sort.sql spark-iceberg:/tmp/07_sort.sql
    @docker exec spark-iceberg spark-sql -f /tmp/07_sort.sql 2>&1 | {{filter}} | tail -1
    @docker exec spark-iceberg python3 /tmp/07_measure.py "sorted by customer_id" 2>&1 | {{filter}}
    docker cp {{repro}}/07-clustering/04_zorder.sql spark-iceberg:/tmp/07_zorder.sql
    @docker exec spark-iceberg spark-sql -f /tmp/07_zorder.sql 2>&1 | {{filter}} | tail -1
    @docker exec spark-iceberg python3 /tmp/07_measure.py "z-ordered on (customer_id, amt)" 2>&1 | {{filter}}

# REPRO #8 — delete one row CoW vs MoR and price both
m08-cost:
    docker cp {{repro}}/08-governance/01_setup.sql spark-iceberg:/tmp/08_setup.sql
    docker exec spark-iceberg spark-sql -f /tmp/08_setup.sql >/dev/null 2>&1
    docker cp {{repro}}/08-governance/02_delete.sql spark-iceberg:/tmp/08_delete.sql
    docker exec spark-iceberg spark-sql -f /tmp/08_delete.sql >/dev/null 2>&1
    docker cp {{repro}}/08-governance/03_measure.py spark-iceberg:/tmp/08_measure.py
    @docker exec spark-iceberg python3 /tmp/08_measure.py 2>&1 | {{filter}}

# ── table health (cross-module) ───────────────────────────────────────────
# small-file metric: avg file size, partition skew, verdict vs the 128MB target
health table="db.events":
    #!/usr/bin/env bash
    set -uo pipefail
    # `just --list` renders this recipe as `health table="db.events"`, so typing
    # that string back looks right -- but just passes the literal
    # `table=db.events`, which reaches pyiceberg as a namespace and produces a
    # twenty-line traceback ending in "Table does not exist: table=db.events".
    # Strip the accidental prefix, then confirm the table loads before handing
    # it to a script whose failure mode is a stack trace.
    t='{{table}}'
    t=${t#table=}
    ns=${t%%.*}; tbl=${t#*.}
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:8181/v1/namespaces/$ns/tables/$tbl")
    if [ "$code" != 200 ]; then
      echo "health: cannot load '$t' (catalog returned $code)" >&2
      echo "        usage: just health db.events      # namespace.table, no 'table=' prefix" >&2
      exit 1
    fi
    docker cp {{repro}}/../tools/health.py spark-iceberg:/tmp/health.py
    docker exec spark-iceberg python3 /tmp/health.py "$t" 2>&1 | {{filter}}

# ── interactive ───────────────────────────────────────────────────────────
# open a spark-sql prompt inside the container
# The leading `-` ignores the exit status: quitting an interactive prompt with
# ctrl-C returns 130, and without this `just` announces "recipe `sql` failed",
# which reads as though the lab broke when nothing did.
sql:
    -docker exec -it spark-iceberg spark-sql

# open a shell in the spark container
shell:
    -docker exec -it spark-iceberg bash

# REPRO #0 — add one file to a Parquet dir vs an Iceberg table: 351 rows vs 300
m00-why:
    docker cp {{repro}}/00-why-iceberg/01_hive_style.py spark-iceberg:/tmp/00_hive_style.py
    @docker exec spark-iceberg python3 /tmp/00_hive_style.py 2>&1 | {{filter}} | grep -A20 "HIVE-STYLE"
    @bash {{repro}}/00-why-iceberg/02_iceberg.sh

# REPRO #9 — two writers, one snapshot: the loser is rejected, then rolled back
m09-concurrent: reset
    docker cp {{repro}}/09-concurrency/01_setup.sql spark-iceberg:/tmp/09_setup.sql
    docker exec spark-iceberg spark-sql -f /tmp/09_setup.sql >/dev/null 2>&1
    docker cp {{repro}}/09-concurrency/02_conflict.py spark-iceberg:/tmp/09_conflict.py
    @docker exec spark-iceberg python3 /tmp/09_conflict.py 2>&1 | {{filter}}
    docker cp {{repro}}/09-concurrency/03_recover.py spark-iceberg:/tmp/09_recover.py
    @docker exec spark-iceberg python3 /tmp/09_recover.py 2>&1 | {{filter}}
    docker cp {{repro}}/09-concurrency/04_timetravel.py spark-iceberg:/tmp/09_timetravel.py
    @docker exec spark-iceberg python3 /tmp/09_timetravel.py 2>&1 | {{filter}}

# REPRO #10 — one row deleted from a v2 and a v3 table: 1,416 bytes vs 42
m10-spec:
    docker cp {{repro}}/10-spec-v3/01_setup.sql spark-iceberg:/tmp/10_setup.sql
    docker exec spark-iceberg spark-sql -f /tmp/10_setup.sql >/dev/null 2>&1
    docker cp {{repro}}/10-spec-v3/02_delete.sql spark-iceberg:/tmp/10_delete.sql
    docker exec spark-iceberg spark-sql -f /tmp/10_delete.sql >/dev/null 2>&1
    docker cp {{repro}}/10-spec-v3/03_measure.py spark-iceberg:/tmp/10_measure.py
    @docker exec spark-iceberg python3 /tmp/10_measure.py 2>&1 | {{filter}}
    docker cp {{repro}}/10-spec-v3/04_lineage.sql spark-iceberg:/tmp/10_lineage.sql
    @docker exec spark-iceberg spark-sql -f /tmp/10_lineage.sql 2>&1 | {{filter}} | grep -E "COMPACTION|sequence"

# REPRO #10c — update 3 rows; 33 report the new sequence number, not 3
m10-sequence:
    docker cp {{repro}}/10-spec-v3/07_sequence.sql spark-iceberg:/tmp/10_sequence.sql
    @docker exec spark-iceberg spark-sql -f /tmp/10_sequence.sql 2>&1 | {{filter}} | grep -E "data files|UPDATE"

# REPRO #10b — turn deletion vectors on for an existing table (added-dvs = 1)
m10-upgrade:
    docker cp {{repro}}/10-spec-v3/06_upgrade.sql spark-iceberg:/tmp/10_upgrade.sql
    docker exec spark-iceberg spark-sql -f /tmp/10_upgrade.sql >/dev/null 2>&1
    docker cp {{repro}}/10-spec-v3/06_report.py spark-iceberg:/tmp/10_report.py
    @docker exec spark-iceberg python3 /tmp/10_report.py 2>&1 | {{filter}}

# REPRO #11 — the whole REST catalog is 31 endpoints; exactly one commits
m11-catalog:
    docker cp {{repro}}/11-catalogs/00_setup.sql spark-iceberg:/tmp/11_setup.sql
    docker exec spark-iceberg spark-sql -f /tmp/11_setup.sql >/dev/null 2>&1
    docker cp {{repro}}/11-catalogs/01_explore.py spark-iceberg:/tmp/11_explore.py
    @docker exec spark-iceberg python3 /tmp/11_explore.py 2>&1 | {{filter}}

# REPRO #11b — DuckDB reads the same catalog (HOST, needs duckdb installed)
m11-duckdb:
    @cd {{repro}}/11-catalogs && duckdb -c ".read 02_duckdb.sql"

# REPRO #14 — after a rollback, main and newest differ and engines disagree
m14-interop:
    docker cp {{repro}}/14-interop/01_setup.sql spark-iceberg:/tmp/14_setup.sql
    docker exec spark-iceberg spark-sql -f /tmp/14_setup.sql >/dev/null 2>&1
    docker cp {{repro}}/14-interop/02_break_and_recover.py spark-iceberg:/tmp/14_break.py
    @docker exec spark-iceberg python3 /tmp/14_break.py 2>&1 | {{filter}}

# REPRO #14b — the third engine's view of that table (HOST, needs duckdb)
m14-duckdb:
    #!/usr/bin/env bash
    # DuckDB 1.5.2 takes only an integer in `AT (VERSION => ...)` -- TAG,
    # BRANCH and a quoted ref name are all rejected by the parser -- and a
    # snapshot id regenerates on every run, so it cannot be committed to the
    # file. Read `main` from the catalog and substitute it, which is exactly
    # what the capture script did when this module was filmed.
    set -euo pipefail
    cd {{repro}}/14-interop
    MAIN=$(curl -s http://localhost:8181/v1/namespaces/db/tables/interop \
      | python3 -c "import json,sys; print(json.load(sys.stdin)['metadata']['refs']['main']['snapshot-id'])")
    if [[ -z "${MAIN:-}" ]]; then
      echo "could not read db.interop's main ref -- run \`just m14-interop\` first" >&2
      exit 1
    fi
    sed "s/__MAIN_SNAPSHOT__/$MAIN/" 03_duckdb.sql > /tmp/m14_duckdb.sql
    tail -3 /tmp/m14_duckdb.sql
    duckdb -c ".read /tmp/m14_duckdb.sql"
