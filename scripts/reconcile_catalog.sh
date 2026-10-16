#!/usr/bin/env bash
# Clear catalog entries whose metadata is gone from object storage.
#
# Bringing the lab up can reset MinIO's warehouse while the REST catalog keeps
# its entries. The table is then listed but unreadable, and because the
# reproduction scripts silence their own stderr, the learner sees blank numbers
# rather than an error -- the worst possible failure. `DROP TABLE IF EXISTS`
# cannot clear it either: the drop loads the table first and the load is what
# fails. The REST DELETE is the only thing that does.
#
# A load returning 404 is the exact signal: the entry exists (it was listed) but
# its metadata does not. Deleting it lets each module's recipe recreate its
# table from scratch, which is what every recipe already does.
#
# Run by `just lab-up`. Safe and silent when there is nothing stale.
set -uo pipefail

CATALOG="${CATALOG:-http://localhost:8181}"

# The catalog answers before it is ready to serve loads; without this the first
# probe can 503 and be mistaken for a healthy table.
for _ in $(seq 1 30); do
  curl -sf "$CATALOG/v1/config" >/dev/null 2>&1 && break
  /bin/sleep 1
done

namespaces=$(curl -sf "$CATALOG/v1/namespaces" 2>/dev/null \
  | python3 -c 'import json,sys
try: print("\n".join("%1F".join(n) for n in json.load(sys.stdin)["namespaces"]))
except Exception: pass' 2>/dev/null)

[[ -z "$namespaces" ]] && exit 0

cleared=0
while IFS= read -r ns; do
  [[ -z "$ns" ]] && continue
  ns_path=${ns//$'\x1f'/%1F}   # a multi-level namespace is %1F-separated in the REST path
  tables=$(curl -sf "$CATALOG/v1/namespaces/$ns_path/tables" 2>/dev/null \
    | python3 -c 'import json,sys
try: print("\n".join(i["name"] for i in json.load(sys.stdin)["identifiers"]))
except Exception: pass' 2>/dev/null)
  while IFS= read -r t; do
    [[ -z "$t" ]] && continue
    code=$(curl -s -o /dev/null -w '%{http_code}' "$CATALOG/v1/namespaces/$ns_path/tables/$t")
    if [[ "$code" == "404" ]]; then
      curl -s -X DELETE "$CATALOG/v1/namespaces/$ns_path/tables/$t?purgeRequested=false" >/dev/null
      echo "  cleared stale entry: ${ns//$'\x1f'/.}.$t"
      cleared=$((cleared + 1))
    fi
  done <<< "$tables"
done <<< "$namespaces"

if (( cleared )); then
  echo "  $cleared stale table(s) cleared -- each module's recipe will recreate its own."
fi
exit 0
