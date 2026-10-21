#!/usr/bin/env bash
# Run a command against the droplet's Postgres through an SSH tunnel (#137).
# Postgres has no public port: this forwards a local port to the db
# container, sets DATABASE_URL (without the password) and PGPASSWORD for the
# command, and closes the tunnel when it exits.
#
#   infra/db-tunnel.sh uv run --extra index python -m scripts.build_index --dry-run
#   infra/db-tunnel.sh psql          # psql reads PGHOST/PGPORT/PGUSER/PGDATABASE
#
# The host is DEPLOY_HOST, else `infra/tofu.sh output -raw ip`; the key is
# PATRISTICA_SSH_KEY (default ~/.ssh/patristica_deploy); the local port is
# DB_TUNNEL_PORT (default 15432). The password is read from the host's .env
# into this process's environment only; it is never printed.
set -euo pipefail

if [[ $# -eq 0 ]]; then
    echo "usage: db-tunnel.sh <command> [args...]" >&2
    exit 2
fi

here="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "${here}/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    . "${here}/.env"
    set +a
fi
host="${DEPLOY_HOST:-$("${here}/tofu.sh" output -raw ip)}"
key="${PATRISTICA_SSH_KEY:-$HOME/.ssh/patristica_deploy}"
port="${DB_TUNNEL_PORT:-15432}"
ssh_opts=(-i "$key" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new)
remote="root@${host}"
log() { echo "db-tunnel: $*" >&2; }

db_ip="$(ssh "${ssh_opts[@]}" "$remote" \
    "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' patristica-db-1")"
[[ -n "$db_ip" ]] || { log "the db container is not running on ${host}"; exit 1; }
PGPASSWORD="$(ssh "${ssh_opts[@]}" "$remote" \
    "sed -n 's/^POSTGRES_PASSWORD=//p' /opt/patristica/compose/.env")"
[[ -n "$PGPASSWORD" ]] || { log "no POSTGRES_PASSWORD in the host .env"; exit 1; }

ssh "${ssh_opts[@]}" -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
    -L "127.0.0.1:${port}:${db_ip}:5432" "$remote" &
tunnel=$!
trap 'kill "$tunnel" 2>/dev/null || true' EXIT
for _ in $(seq 1 50); do
    if (echo >"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
        break
    fi
    kill -0 "$tunnel" 2>/dev/null || { log "the tunnel failed to start"; exit 1; }
    sleep 0.2
done
log "tunnel to ${db_ip}:5432 on ${host} at 127.0.0.1:${port}"

export PGPASSWORD PGHOST=127.0.0.1 PGPORT="$port" PGUSER=patristica PGDATABASE=patristica
export DATABASE_URL="postgresql://patristica@127.0.0.1:${port}/patristica"
"$@"
