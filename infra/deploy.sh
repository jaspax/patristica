#!/usr/bin/env bash
# Deploy the compose stack to the database host. Safe to re-run: it syncs
# infra/compose and the API and web source, rewrites the host's .env (on the
# data volume; it keeps the Postgres password, which is generated there once
# and never leaves the box), installs the backup timer and the prewarm unit,
# runs `docker compose up --build` and loads the search index into the page
# cache (compose/postgres/prewarm.sh).
#
#   infra/deploy.sh            # host, hostnames and keys from `infra/tofu.sh output`
#   DEPLOY_HOST=1.2.3.4 API_DOMAIN=1-2-3-4.sslip.io WEB_DOMAIN=… infra/deploy.sh   # override
#
#   DEPLOY_HOST=… API_DOMAIN=… WEB_DOMAIN=… infra/deploy.sh --keep-env
#       Code only, for the Deploy workflow (.github/workflows/deploy.yml): leaves
#       the host's .env as it is, so it needs neither infra/.env nor tofu. A
#       change that adds a host .env setting needs one full run first.
set -euo pipefail

keep_env=false
case "${1:-}" in
    --keep-env) keep_env=true ;;
    "") ;;
    *) echo "usage: deploy.sh [--keep-env]" >&2; exit 2 ;;
esac

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$here")"
env_file="${here}/.env"
if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck source=/dev/null
    . "$env_file"
    set +a
elif ! $keep_env; then
    echo "deploy.sh: ${env_file} not found (copy .env.example)" >&2
    exit 1
fi

if $keep_env; then
    host="${DEPLOY_HOST:?--keep-env needs DEPLOY_HOST}"
    api_domain="${API_DOMAIN:?--keep-env needs API_DOMAIN}"
    web_domain="${WEB_DOMAIN:?--keep-env needs WEB_DOMAIN}"
else
    host="${DEPLOY_HOST:-$("${here}/tofu.sh" output -raw ip)}"
    api_domain="${API_DOMAIN:-$("${here}/tofu.sh" output -raw api_hostname)}"
    # The web app's hostname (apex); www.<it> redirects to it. DNS is by hand at
    # Cloudflare (infra/README.md), so tofu doesn't need to know it.
    web_domain="${WEB_DOMAIN:-patristica.app}"
    library_url="${LIBRARY_URL:-$("${here}/tofu.sh" output -raw library_url)}"
    backups_bucket="$("${here}/tofu.sh" output -raw backups_bucket)"
    backups_access="$("${here}/tofu.sh" output -raw backups_access_key)"
    backups_secret="$("${here}/tofu.sh" output -raw backups_secret_key)"
    # The search API's query embeddings (#141): from the environment, infra/.env
    # or the repo-root .env (where scripts.embed reads it).
    voyage_key="${VOYAGE_API_KEY:-$(sed -n 's/^VOYAGE_API_KEY=//p' "${repo}/.env" 2>/dev/null || true)}"
    [[ -n "$voyage_key" ]] || echo "deploy: VOYAGE_API_KEY not found; /search will answer 503" >&2
fi
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
(cd "$repo" && rsync -az --no-owner --no-group --delete --relative -e "ssh ${ssh_opts[*]}" \
    --exclude __pycache__ --exclude node_modules --exclude .next --exclude '.env*' \
    --exclude .vercel --exclude public/library \
    pyproject.toml uv.lock patristica/ api/ web/ "${remote}:/opt/patristica/src/")

if $keep_env; then
    log "keeping the host .env"
    ssh "${ssh_opts[@]}" "$remote" 'test -e /opt/patristica/compose/.env' \
        || { log "no .env on the host yet: run infra/deploy.sh without --keep-env once"; exit 1; }
else
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
WEB_DOMAIN=${web_domain}
WWW_DOMAIN=www.${web_domain}
LIBRARY_URL=${library_url}
PGDATA_DIR=/mnt/pgdata/postgres
SRC_DIR=/opt/patristica/src
BACKUP_BUCKET=${backups_bucket}
RCLONE_CONFIG_SPACES_TYPE=s3
RCLONE_CONFIG_SPACES_PROVIDER=DigitalOcean
RCLONE_CONFIG_SPACES_ENDPOINT=nyc3.digitaloceanspaces.com
RCLONE_CONFIG_SPACES_ACCESS_KEY_ID=${backups_access}
RCLONE_CONFIG_SPACES_SECRET_ACCESS_KEY=${backups_secret}
RCLONE_CONFIG_SPACES_NO_CHECK_BUCKET=true
VOYAGE_API_KEY=${voyage_key}"
    # shellcheck disable=SC2029  # write_env is a fixed script; the secrets go on stdin
    printf '%s\n' "$env_body" | ssh "${ssh_opts[@]}" "$remote" "$write_env"
fi

log "installing backup timer and prewarm unit, starting the stack"
ssh "${ssh_opts[@]}" "$remote" 'set -euo pipefail
cd /opt/patristica/compose
install -m 644 backup/patristica-backup.service backup/patristica-backup.timer \
    postgres/patristica-prewarm.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now patristica-backup.timer
systemctl enable patristica-prewarm.service
docker compose up -d --build --remove-orphans --wait
docker image prune -f >/dev/null
systemctl start patristica-prewarm.service \
    || echo "deploy: prewarm failed (journalctl -u patristica-prewarm)" >&2'

# Retries for about two minutes: Caddy may still be getting a certificate.
check() {
    for _ in $(seq 1 20); do
        if curl -fsS -o /dev/null "$1"; then
            log "ok: $1"
            return 0
        fi
        sleep 6
    done
    log "health check failed: $1"
    return 1
}

failed=0
check "https://${api_domain}/healthz" || failed=1
check "https://${web_domain}/" || failed=1
check "https://${web_domain}/api/healthz" || failed=1
check "https://www.${web_domain}/" || failed=1
if [[ "$failed" -ne 0 ]]; then
    log "see: ssh -i ${key} ${remote} 'cd /opt/patristica/compose && docker compose logs'"
    exit 1
fi
log "done"
