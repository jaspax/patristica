#!/usr/bin/env bash
# Run OpenTofu on infra/tofu with credentials from infra/.env.
#   infra/tofu.sh init | plan | apply | output -raw ip | ...
# `init` gets the R2 backend settings (bucket, endpoint) added automatically.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
env_file="${here}/.env"
[[ -f "$env_file" ]] || { echo "tofu.sh: ${env_file} not found (copy .env.example)" >&2; exit 1; }
set -a
# shellcheck source=/dev/null
. "$env_file"
set +a

: "${DIGITALOCEAN_TOKEN:?set in infra/.env}"
: "${R2_ACCOUNT_ID:?set in infra/.env}"
: "${R2_INFRA_BUCKET:?set in infra/.env}"
export AWS_ACCESS_KEY_ID="${R2_INFRA_ACCESS_KEY_ID:?set in infra/.env}"
export AWS_SECRET_ACCESS_KEY="${R2_INFRA_SECRET_ACCESS_KEY:?set in infra/.env}"

tofu=(tofu -chdir="${here}/tofu")
if [[ "${1:-}" == "init" ]]; then
    shift
    exec "${tofu[@]}" init \
        -backend-config="bucket=${R2_INFRA_BUCKET}" \
        -backend-config="endpoints={s3=\"https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com\"}" \
        "$@"
fi
exec "${tofu[@]}" "$@"
