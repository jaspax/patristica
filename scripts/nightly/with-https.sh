#!/usr/bin/env bash
# Run a command with git (and git-lfs) talking to GitHub over HTTPS through
# gh's credentials (#425). This machine has no GitHub SSH key and origin is an
# SSH URL, so pushes, fetches and LFS transfers need this. The nightly agent's
# allowlist (.claude/settings.json) names this script, never an env prefix.
#
#   scripts/nightly/with-https.sh git fetch https://github.com/jaspax/patristica.git master
#   scripts/nightly/with-https.sh uv run python -m scripts.data pull --job tests
set -euo pipefail
export GIT_CONFIG_COUNT=2
export GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0='!gh auth git-credential'
export GIT_CONFIG_KEY_1=lfs.url GIT_CONFIG_VALUE_1=https://github.com/jaspax/patristica.git/info/lfs
exec "$@"
