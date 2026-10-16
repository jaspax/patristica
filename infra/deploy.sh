#!/usr/bin/env bash
# Deploy the compose stack to the database host. Safe to re-run: it syncs
# infra/compose and the API source, rewrites the host's .env (on the data
# volume; it keeps the Postgres password, which is generated there once and
# never leaves the box),
# installs the backup timer and runs `docker compose up`.
#
#   infra/deploy.sh            # host and hostname from `infra/tofu.sh output`
#   DEPLOY_HOST=1.2.3.4 API_DOMAIN=1-2-3-4.sslip.io infra/deploy.sh   # override
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$here")"
env_file="${here}/.env"
[[ -f "$env_file" ]] || { echo "deploy.sh: ${env_file} not found (copy .env.example)" >&2; exit 1; }
set -a
# shellcheck source=/dev/null
. "$env_file"
set +a

host="${DEPLOY_HOST:-$("${here}/tofu.sh" output -raw ip)}"
api_domain="${API_DOMAIN:-$("${here}/tofu.sh" output -raw api_hostname)}"
backups_bucket="$("${here}/tofu.sh" output -raw backups_bucket)"
backups_access="$("${here}/tofu.sh" output -raw backups_access_key)"
backups_secret="$("${here}/tofu.sh" output -raw backups_secret_key)"
key="${PATRISTICA_SSH_KEY:-$HOME/.ssh/patristica_deploy}"
ssh_opts=(-i "$key" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new)
remote="root@${host}"
log() { echo "deploy: $*" >&2; }

log "waiting for cloud-init on ${host}"
# Exit 2 means done with recoverable errors (warnings); 1 means a failed module.
ssh "${ssh_opts[@]}" "$remote" 'rc=0; cloud-init status --wait >/dev/null || rc=$?
if [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ]; then cloud-init status --long >&2; exit 1; fi
mountpoint -q /mnt/pgdata && command -v docker >/dev/null'

log "syncing files"
rsync -az --no-owner --no-group --delete --exclude .env -e "ssh ${ssh_opts[*]}" \
    "${here}/compose/" "${remote}:/opt/patristica/compose/"
(cd "$repo" && rsync -az --no-owner --no-group --delete --relative --exclude __pycache__ -e "ssh ${ssh_opts[*]}" \
    pyproject.toml uv.lock patristica/ api/ "${remote}:/opt/patristica/src/")

log "writing the host .env"
# Secrets go over stdin, never on a command line.
read -r -d '' write_env <<'EOF' || true
set -euo pipefail
umask 077
# Kept on the data volume, so a rebuilt droplet keeps the Postgres password.
f=/mnt/pgdata/compose.env
pw=$(sed -n 's/^POSTGRES_PASSWORD=//p' "$f" 2>/dev/null || true)
[ -n "$pw" ] || pw=$(openssl rand -hex 24)
{ echo "POSTGRES_PASSWORD=$pw"; cat; } > "$f.new"
mv "$f.new" "$f"
ln -sfn "$f" /opt/patristica/compose/.env
EOF
env_body="API_DOMAIN=${api_domain}
PGDATA_DIR=/mnt/pgdata/postgres
SRC_DIR=/opt/patristica/src
BACKUP_BUCKET=${backups_bucket}
RCLONE_CONFIG_SPACES_TYPE=s3
RCLONE_CONFIG_SPACES_PROVIDER=DigitalOcean
RCLONE_CONFIG_SPACES_ENDPOINT=nyc3.digitaloceanspaces.com
RCLONE_CONFIG_SPACES_ACCESS_KEY_ID=${backups_access}
RCLONE_CONFIG_SPACES_SECRET_ACCESS_KEY=${backups_secret}
RCLONE_CONFIG_SPACES_NO_CHECK_BUCKET=true"
# shellcheck disable=SC2029  # write_env is a fixed script; the secrets go on stdin
printf '%s\n' "$env_body" | ssh "${ssh_opts[@]}" "$remote" "$write_env"

log "installing backup timer and starting the stack"
ssh "${ssh_opts[@]}" "$remote" 'set -euo pipefail
cd /opt/patristica/compose
install -m 644 backup/patristica-backup.service backup/patristica-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now patristica-backup.timer
docker compose up -d --build --remove-orphans --wait
docker image prune -f >/dev/null'

log "checking https://${api_domain}/healthz"
for _ in $(seq 1 20); do
    if curl -fsS "https://${api_domain}/healthz"; then
        echo
        log "done"
        exit 0
    fi
    sleep 6
done
log "health check failed; see: ssh -i ${key} ${remote} 'cd /opt/patristica/compose && docker compose logs'"
exit 1
