#!/usr/bin/env bash
# Run OpenTofu on infra/tofu with credentials from infra/.env.
#   infra/tofu.sh init | plan | apply | output -raw ip | ...
# `init` gets the state bucket added automatically. Run
# `uv run --extra deploy python -m scripts.bootstrap_infra` once first.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
env_file="${here}/.env"
[[ -f "$env_file" ]] || { echo "tofu.sh: ${env_file} not found (copy .env.example)" >&2; exit 1; }
set -a
# shellcheck source=/dev/null
. "$env_file"
set +a

: "${DIGITALOCEAN_TOKEN:?set in infra/.env}"
missing="run scripts.bootstrap_infra first"
export SPACES_ACCESS_KEY_ID="${SPACES_ACCESS_KEY_ID:?$missing}"
export SPACES_SECRET_ACCESS_KEY="${SPACES_SECRET_ACCESS_KEY:?$missing}"
export AWS_ACCESS_KEY_ID="$SPACES_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$SPACES_SECRET_ACCESS_KEY"

tofu=(tofu -chdir="${here}/tofu")
if [[ "${1:-}" == "init" ]]; then
    shift
    exec "${tofu[@]}" init \
        -backend-config="bucket=${SPACES_STATE_BUCKET:-patristica-tfstate}" \
        "$@"
fi
exec "${tofu[@]}" "$@"
