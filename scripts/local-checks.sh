#!/usr/bin/env bash
# The deterministic pre-PR gate. The dispatcher runs this after
# /implement-mainspec and before opening a PR (two-strike: `fix` -> agent ->
# STUCK at the cap). Correctness, not coverage — see AGENTS.md's verification
# section for what backs (or, today, doesn't back) each layer.
#
#   ./scripts/local-checks.sh        check (exit 0 = pass)
#   ./scripts/local-checks.sh fix    autofix the auto-fixable subset
#
# Neither stack has lint/format, typecheck, or a test suite wired up yet (no
# eslint config despite frontend/package.json's `lint` script, no ruff/mypy,
# no pytest/vitest — see AGENTS.md). There is nothing to autofix and nothing
# to run beyond the custom invariant lints below, so `fix` is currently a
# no-op. When real tooling is added, wire it in here, fastest-to-slowest,
# ahead of the lints loop (see references/local-checks-design.md in the
# env-init skill for the responsibilities this script owns).
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

mode="${1:-check}"

if [[ "$mode" == "fix" ]]; then
  echo "local-checks: no autofixable checks are wired up yet — nothing to do."
  exit 0
fi

# --- scripts/lints/ — grows over time via /learn and by hand ---
status=0
shopt -s nullglob
for lint in scripts/lints/*.sh; do
  echo "local-checks: running ${lint}"
  if ! "$lint"; then
    status=1
  fi
done
shopt -u nullglob

exit "$status"
