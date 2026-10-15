#!/usr/bin/env bash
# Nightly pg_dump of the patristica database to the private R2 infra bucket,
# keeping about two weeks of dumps. Run by patristica-backup.timer on the
# database host; reads the rclone remote "r2" and R2_INFRA_BUCKET from .env.
set -euo pipefail

cd "$(dirname "$0")/.."
set -a
# shellcheck source=/dev/null
. ./.env
set +a

prefix="r2:${R2_INFRA_BUCKET:?}/pg-backups"
name="patristica-$(date -u +%Y%m%dT%H%MZ).dump"
keep_days="${BACKUP_KEEP_DAYS:-15}"

# Upload under a .partial name and rename on success, so an interrupted dump
# never looks like a complete backup.
docker compose exec -T db pg_dump -U patristica -d patristica --format=custom \
    | rclone rcat "${prefix}/${name}.partial"
rclone moveto "${prefix}/${name}.partial" "${prefix}/${name}"
echo "backup: uploaded ${prefix}/${name}"

rclone delete --min-age "${keep_days}d" "${prefix}/"
