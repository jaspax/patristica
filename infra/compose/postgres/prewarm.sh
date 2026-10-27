#!/usr/bin/env bash
# Load the search indexes into the OS page cache (#252): every per-model HNSW
# index (chunk_vectors_hnsw_m*), chunks_pkey and passage_groups_pkey, with
# pg_prewarm(…, 'prefetch'). Prefetch only asks the kernel to read the files
# ahead, so it returns at once and doesn't fill shared_buffers (autoprewarm
# restores those). Idempotent; on a fresh database without the indexes it
# warms whatever exists, possibly nothing.
#
# Run by patristica-prewarm.service at boot and by infra/deploy.sh after
# `docker compose up`, and by backup/pg-backup.sh after the nightly dump,
# which streams the whole database through the page cache.
set -euo pipefail

cd "$(dirname "$0")/.."

# At boot the db container may still be starting.
wait_seconds="${PREWARM_WAIT_SECONDS:-600}"
waited=0
until docker compose exec -T db pg_isready -q -U patristica -d patristica 2>/dev/null; do
    if (( waited >= wait_seconds )); then
        echo "prewarm: database not ready after ${wait_seconds}s" >&2
        exit 1
    fi
    sleep 5
    waited=$((waited + 5))
done

docker compose exec -T db psql -U patristica -d patristica -v ON_ERROR_STOP=1 -qAt <<'SQL'
SET client_min_messages = warning;
CREATE EXTENSION IF NOT EXISTS pg_prewarm;
SELECT format('prewarm: %s, %s (%s blocks)', c.relname,
              pg_size_pretty(pg_relation_size(c.oid)), pg_prewarm(c.oid, 'prefetch'))
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = current_schema() AND c.relkind = 'i'
  AND (c.relname LIKE 'chunk\_vectors\_hnsw\_m%'
       OR c.relname IN ('chunks_pkey', 'passage_groups_pkey'))
ORDER BY c.relname;
SQL
