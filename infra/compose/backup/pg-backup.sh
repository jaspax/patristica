#!/usr/bin/env bash
# Nightly pg_dump of the patristica database to the private Spaces backups
# bucket. Run by patristica-backup.timer on the database host; reads the
# rclone remote "spaces" and BACKUP_BUCKET from .env. Old dumps are expired
# by the bucket's lifecycle rule (infra/tofu/main.tf), not here.
set -euo pipefail

cd "$(dirname "$0")/.."
set -a
# shellcheck source=/dev/null
. ./.env
set +a

# The dump reads the whole database through the page cache and evicts the
# search index; load it again afterwards, whether or not the dump succeeded.
trap 'postgres/prewarm.sh || echo "backup: prewarm failed" >&2' EXIT

prefix="spaces:${BACKUP_BUCKET:?}/pg-backups"
name="patristica-$(date -u +%Y%m%dT%H%MZ).dump"

# Upload under a .partial name and rename on success, so an interrupted dump
# never looks like a complete backup.
docker compose exec -T db pg_dump -U patristica -d patristica --format=custom \
    | rclone rcat "${prefix}/${name}.partial"
rclone moveto "${prefix}/${name}.partial" "${prefix}/${name}"
echo "backup: uploaded ${prefix}/${name}"
