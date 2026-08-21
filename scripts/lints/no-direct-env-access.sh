#!/usr/bin/env bash
# Invariant: all backend config flows through backend/config.py's Settings —
# no file reads os.getenv/os.environ directly. Locked in from the original
# scaffold commit ("All secrets via environment variables; no hardcoded
# values") and evidenced by 0 violations across the current codebase.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

hits=$(grep -rnE 'os\.(getenv|environ)' backend --include='*.py' \
  | grep -v '^backend/config\.py:' \
  | grep -v '/venv/' || true)

if [[ -n "$hits" ]]; then
  echo "❌ direct os.getenv/os.environ access outside backend/config.py:" >&2
  echo "$hits" >&2
  echo >&2
  echo "WHY: every setting is a validated, documented field on Settings" >&2
  echo "     (backend/config.py) — a stray os.getenv bypasses validation," >&2
  echo "     .env.example documentation, and CORS/rate-limit config that" >&2
  echo "     reads from the same object. This was a deliberate decision" >&2
  echo "     from the project's first commit, not an accident." >&2
  echo "FIX: add a field to Settings in backend/config.py, add the matching" >&2
  echo "     key to backend/.env.example, and read it via get_settings()." >&2
  echo "DON'T-CHEAT: don't wrap the os.getenv call in a helper to dodge the" >&2
  echo "     grep — the fix is routing through Settings, not hiding the call." >&2
  exit 1
fi

exit 0
