# Repro #11 — the catalog is an HTTP contract, and you can read it with curl

**Goal:** stop treating the catalog as the thing that holds the pointer and
actually open it. Every call here is plain HTTP against the REST spec — no
Iceberg library, no Spark — because the point of the REST catalog is that the
*contract*, not the client, is what engines agree on. Then a second engine that
shares no code with the first reads a table Spark wrote. The concrete version of
Module 11.

## Stack
docker-spark-iceberg's `iceberg-rest` container, reachable at `http://rest:8181`
from inside the network and `http://localhost:8181` from the host. Plus DuckDB
**1.5.2** on the host, which is the second engine.

`01_explore.py` uses only `urllib` from the standard library, deliberately:
importing an Iceberg client would undercut the claim it is making.

## Run
```bash
just m11-catalogs
# or manually:
docker exec spark-iceberg python3 /tmp/11_explore.py      # layers 1-4
duckdb -c ".read 02_duckdb.sql"                            # layer 5, from the HOST
```

## Measured result (these become the module hooks)

### 1. The catalog announces its own interface

```
GET /v1/config  ->  31 endpoints advertised
  POST v1/oauth/tokens
  GET  v1/config
  GET  /v1/{prefix}/namespaces
  POST /v1/{prefix}/namespaces
  HEAD /v1/{prefix}/namespaces/{namespace}
  ...
```

Thirty-one endpoints is the entire interface. Anything that speaks these verbs
is an Iceberg catalog client — there is no shared-library requirement anywhere
in the design.

### 2. Loading a table is one GET that returns one pointer

```
GET /v1/namespaces/db/tables          -> ['clustering','concurrent','gov_cow','gov_mor']
GET /v1/namespaces/db/tables/clustering
  metadata-location   s3://warehouse/db/clustering/metadata/00008-....metadata.json
  format-version      2
  current-snapshot-id 1790023505614939963
  snapshots           8
```

**One URL, one pointer.** Everything else the engine needs it reads from object
storage itself, walking the tree from Module 01. The catalog is not in the data
path at all.

### 3. Exactly one endpoint is transactional

```
the one endpoint that moves the pointer:
  POST /v1/{prefix}/namespaces/{namespace}/tables/{table}      (advertised)
neighbours on the same path, which do not commit anything:
  metrics    POST .../tables/{table}/metrics
  plan       POST .../tables/{table}/plan
  tasks      POST .../tables/{table}/tasks
```

Module 02's compare-and-swap and Module 09's rejected writer are both this one
call: the writer sends its new metadata *and* the requirement that the ref has
not moved, and the catalog either swaps or refuses. Nothing else in the stack is
transactional.

### 4. What did NOT come back: credentials

```
config.defaults    {}
config.overrides   {'namespace-separator': '%2E'}
table config       {}
```

Empty. This catalog vends **no** storage credentials — which is exactly why
every script in this course passes `s3.access-key-id` by hand. Credential
vending is the feature that removes that: the catalog returns scoped,
short-lived credentials for the one table you asked for, so the engine never
holds warehouse-wide keys.

It is not enabled here, and **its absence is the thing you can actually see.**
That is a better way to teach it than a description of a feature nobody in the
room has configured.

### 5. A second engine, over the same contract

DuckDB 1.5.2, on the host, sharing no library and no configuration with Spark:

```sql
INSTALL iceberg; LOAD iceberg;
CREATE SECRET (TYPE s3, KEY_ID 'admin', SECRET 'password',
               ENDPOINT 'localhost:9000', USE_SSL false, URL_STYLE 'path');
ATTACH 'warehouse' AS ice (TYPE iceberg,
       ENDPOINT 'http://localhost:8181', AUTHORIZATION_TYPE 'none');
```

```
ice.db.clustering / concurrent / gov_cow / gov_mor     <- all written by Spark

SELECT count(*), count(DISTINCT customer_id) FROM ice.db.gov_cow;
  rows 4999   customers 1000
```

4,999 is Module 08's copy-on-write delete, seen from a different engine. "Which
engine wrote it" stops being a question anyone has to ask.

## Notes / gotchas

- **`AUTHORIZATION_TYPE 'none'` is required** for the DuckDB attach. Without it
  DuckDB assumes oauth2 and fails with `no 'secret' was provided`. This single
  parameter is the most likely thing to block someone reproducing this.
- **Match the commit endpoint exactly.** Filtering the advertised list for
  `tables/{table}` returns four endpoints — the commit plus `metrics`, `plan`
  and `tasks` — and captioning all four as "the commit endpoint" is wrong.
- **`02_duckdb.sql` reads `db.gov_cow`, not `db.concurrent`,** and that choice is
  deliberate. `db.concurrent` has been rolled back, and DuckDB 1.5.2 resolves
  the latest snapshot rather than the branch ref, so it reports 240 rows where
  pyiceberg reports 340. That divergence is Module 14's headline
  (`reproductions/14-interop/FINDINGS.md`); showing it here would contradict
  Module 09 on screen with no explanation.
- DuckDB rejects `AS ""` — an empty delimited identifier is a parser error. Use
  a named alias for the section headers.
- The advertised endpoint list includes `POST https://auth-server.com/token`, a
  placeholder from the reference implementation. Do not read it as a real
  dependency.

## Not demonstrated in this lab

- **Credential vending working.** This catalog does not implement it, so the
  repro can only show the empty config where the credentials would be. Teach the
  mechanism from the spec and the absence from the measurement; do not fabricate
  a vended-credential response.
- **Polaris, Nessie, Unity Catalog, Glue.** Only the reference REST catalog runs
  here. What *is* transferable is layer 1: those products differ in governance,
  auth and multi-engine policy, not in the table-loading contract, and this
  repro shows precisely how small that contract is. Teach them as implementations
  of these 31 endpoints plus their own opinions, rather than as four separate
  systems to memorise.
- **Catalog migration** (moving a table between catalogs via `register_table`).
  It would need a second catalog implementation running alongside this one.
