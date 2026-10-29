#!/usr/bin/env bash
# Start the nightly machine-translation agent (#425).
#
# Run by the systemd user timer patristica-nightly-mt.timer (22:15
# America/Chicago), or by hand. It checks that the main checkout can do the
# night's work, logs a start line, and starts a background Claude Code
# session running the project skill /nightly-translate, which does the rest
# and reports on the tracking issue. Install: docs/machine-translation.md ->
# "Nightly runs".
#
#   scripts/nightly/run.sh            # start tonight's session
#   scripts/nightly/run.sh --check    # only the checks
set -euo pipefail

main="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$main"
mkdir -p logs
log="logs/nightly-mt-runs.log"
stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }
fail() {
    echo "$(stamp) not started: $*" >>"$log"
    echo "nightly-mt: $*" >&2
    exit 1
}

[[ -d .git && -f scripts/machine_translate.py && -d data/normalized ]] ||
    fail "$main is not the main checkout with scripts.machine_translate and data/normalized"
[[ -f .claude/skills/nightly-translate/SKILL.md ]] || fail "the /nightly-translate skill is missing"
gh auth status >/dev/null 2>&1 || fail "gh is not logged in"
command -v claude >/dev/null || fail "claude is not on PATH"
# The agent works in its own worktree but reads data/normalized here: local
# changes to tracked files would mean it reads something master doesn't have.
[[ -z "$(git status --porcelain --untracked-files=no)" ]] ||
    fail "the main checkout has uncommitted changes"

if [[ "${1:-}" == "--check" ]]; then
    echo "nightly-mt: checks passed"
    exit 0
fi

name="nightly-mt-$(date +%F)"
echo "$(stamp) starting $name" >>"$log"
# dontAsk: what .claude/settings.json allows runs, and everything else is
# denied instead of waiting for a prompt nobody will answer.
claude --bg --name "$name" --model sonnet --permission-mode dontAsk "/nightly-translate" \
    >>"$log" 2>&1 || fail "claude --bg failed (see above)"
