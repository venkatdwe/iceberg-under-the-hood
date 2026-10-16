"""Repro #11 — the catalog is an HTTP contract, and you can read it with curl.

Run: docker exec spark-iceberg python3 /tmp/11_explore.py

Modules 01-09 treated the catalog as the thing that holds the pointer. This
opens it. Every call here is plain HTTP against the REST spec — no Iceberg
library, no Spark — because the point of the REST catalog is that the contract,
not the client, is what engines agree on.

Uses only urllib from the standard library, deliberately: adding a dependency
would undercut the claim that any HTTP client can do this.
"""
import json
import os
import urllib.request

BASE = os.environ.get("ICEBERG_REST", "http://rest:8181")
NS = "db"
TABLE = "catalog_demo"          # this module's own — see 00_setup.sql


def get(path: str):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as r:
        return json.load(r)


# ── LAYER 1: the catalog announces what it can do ─────────────────────────
print("\n========== LAYER 1: THE CATALOG IS A CONTRACT ==========")
cfg = get("/v1/config")
endpoints = cfg.get("endpoints", [])
print(f"  GET /v1/config  ->  {len(endpoints)} endpoints advertised")
for e in endpoints[:6]:
    print(f"    {e}")
print(f"    ... and {max(0, len(endpoints) - 6)} more")
print("  -> this is the whole interface. Any client that speaks these verbs is")
print("     an Iceberg catalog client; there is no shared library requirement.")

# ── LAYER 2: a table load returns exactly one pointer ─────────────────────
print("\n========== LAYER 2: LOADING A TABLE IS ONE GET ==========")
tables = get(f"/v1/namespaces/{NS}/tables").get("identifiers", [])
names = [t["name"] for t in tables]
print(f"  GET /v1/namespaces/{NS}/tables  ->  {len(names)} tables")
# Deliberately NOT names[0]. A catalog can list a table whose metadata is gone —
# this lab does exactly that after a teardown, and loadTable then returns 404.
# Listing and loading are different endpoints and can disagree, which is itself
# worth knowing about a catalog.
target = TABLE if TABLE in names else (names[0] if names else None)
if target:
    doc = get(f"/v1/namespaces/{NS}/tables/{target}")
    meta = doc.get("metadata", {})
    print(f"  GET .../tables/{target}")
    print(f"    metadata-location   {doc.get('metadata-location')}")
    print(f"    format-version      {meta.get('format-version')}")
    print(f"    current-snapshot-id {meta.get('current-snapshot-id')}")
    print(f"    snapshots           {len(meta.get('snapshots') or [])}")
    print("  -> one URL, one pointer. Everything else the engine needs it reads")
    print("     from object storage itself, following the tree from Module 01.")

# ── LAYER 3: the commit endpoint is where atomicity lives ─────────────────
print("\n========== LAYER 3: WHERE THE COMMIT HAPPENS ==========")
# Exactly one endpoint commits. The others under the same path do scan
# planning and metrics reporting — matching loosely on "tables/{table}"
# printed four and called them all the commit, which is not true.
COMMIT = "POST /v1/{prefix}/namespaces/{namespace}/tables/{table}"
others = [e for e in endpoints
          if e.startswith(COMMIT) and e != COMMIT]
print("  the one endpoint that moves the pointer:")
print(f"    {COMMIT}      {'(advertised)' if COMMIT in endpoints else '(NOT advertised)'}")
if others:
    print("  neighbours on the same path, which do not commit anything:")
    for e in others:
        print(f"    {e.rsplit('/', 1)[-1]:<10} {e}")
print("  -> Module 02's compare-and-swap and Module 09's rejected writer are")
print("     both this one call. The writer sends its new metadata AND the")
print("     requirement that the ref has not moved; the catalog checks and")
print("     either swaps or refuses. Nothing else in the stack is transactional.")

# ── LAYER 4: what did NOT come back ───────────────────────────────────────
print("\n========== LAYER 4: NO CREDENTIALS CAME BACK ==========")
defaults, overrides = cfg.get("defaults", {}), cfg.get("overrides", {})
tbl_cfg = {}
if target:
    tbl_cfg = get(f"/v1/namespaces/{NS}/tables/{target}").get("config", {})
print(f"  config.defaults    {defaults}")
print(f"  config.overrides   {overrides}")
print(f"  table config       {tbl_cfg}")
print("  -> empty. This catalog vends NO storage credentials, so every client")
print("     must already hold its own S3 keys — which is why every script in")
print("     this course passes s3.access-key-id by hand.")
print("     Credential vending is the feature that removes that: the catalog")
print("     returns scoped, short-lived credentials for the one table you")
print("     asked for, so the engine never holds warehouse-wide keys.")
print("     Not enabled here — and its absence is exactly what you can see.")
