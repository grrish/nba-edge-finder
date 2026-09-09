#!/usr/bin/env bash
# Definition of done for polymarket-live-data. The harness checks only the exit code.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

BACKEND_PORT="${PORT:-8097}"
PY="$REPO_ROOT/backend/venv/bin/python3"

# ---------------------------------------------------------------------------
# 1. PolymarketService accepts a sport/tag parameter, and it's actually wired
#    through to real, live data (not accepted-and-ignored).
# ---------------------------------------------------------------------------
echo "--- Checking PolymarketService.get_nba_markets(tag_slug=...) ---"

"$PY" - <<'PYEOF'
import sys
sys.path.insert(0, "backend")

from services.polymarket import PolymarketService

svc = PolymarketService()

try:
    nba = svc.get_nba_markets(tag_slug="nba")
    wnba = svc.get_nba_markets(tag_slug="wnba")
except TypeError as exc:
    print(f"get_nba_markets does not accept a tag_slug parameter: {exc}", file=sys.stderr)
    sys.exit(1)

if not wnba:
    print("get_nba_markets(tag_slug='wnba') returned no markets — live WNBA data not reachable", file=sys.stderr)
    sys.exit(1)

nba_ids = {m["market_id"] for m in nba}
wnba_ids = {m["market_id"] for m in wnba}
if nba_ids == wnba_ids:
    print("tag_slug='nba' and tag_slug='wnba' returned identical markets — parameter is not wired through", file=sys.stderr)
    sys.exit(1)

def is_live(m):
    # A resolved/stale market settles outcomePrices to exactly 0/1; the real
    # "is this market actually open" signal is a genuine bid/ask spread, the
    # same test _is_relevant() and the module's own __main__ smoke test use.
    return 0.01 < (m["best_ask"] - m["best_bid"]) < 0.99

live = [m for m in wnba if is_live(m)]
if not live:
    print("no wnba market has a genuine (non-resolved) bid/ask spread", file=sys.stderr)
    sys.exit(1)

m = live[0]
if not m.get("question"):
    print("live wnba market has an empty question", file=sys.stderr)
    sys.exit(1)

print(f"OK — {len(live)} live wnba markets (of {len(wnba)} total), sample: {m['question']!r}")
PYEOF

# ---------------------------------------------------------------------------
# 2. GET /api/v1/games/markets returns real market data over HTTP,
#    independent of scheduled-game matching.
# ---------------------------------------------------------------------------
echo "--- Checking GET /api/v1/games/markets ---"

if curl -sf "http://localhost:${BACKEND_PORT}/health" >/dev/null 2>&1; then
  echo "port ${BACKEND_PORT} is already serving something (not started by this runner) — set PORT to a free port" >&2
  exit 1
fi

( cd backend && "$PY" -m uvicorn main:app --port "$BACKEND_PORT" >/tmp/polymarket-live-data-backend.log 2>&1 & )
SERVER_PID=""
cleanup() {
  if [[ -n "$SERVER_PID" ]]; then kill "$SERVER_PID" 2>/dev/null || true; fi
  pkill -f "uvicorn main:app --port $BACKEND_PORT" 2>/dev/null || true
}
trap cleanup EXIT

for _ in $(seq 1 30); do
  if curl -sf "http://localhost:${BACKEND_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
if ! curl -sf "http://localhost:${BACKEND_PORT}/health" >/dev/null 2>&1; then
  echo "backend never came up on :${BACKEND_PORT} — see /tmp/polymarket-live-data-backend.log" >&2
  cat /tmp/polymarket-live-data-backend.log >&2 || true
  exit 1
fi

http_code=$(curl -s -o /tmp/polymarket-live-data-response.json -w '%{http_code}' \
  "http://localhost:${BACKEND_PORT}/api/v1/games/markets?tag_slug=wnba")
if [[ "$http_code" != "200" ]]; then
  echo "GET /api/v1/games/markets?tag_slug=wnba returned $http_code, expected 200" >&2
  cat /tmp/polymarket-live-data-response.json >&2 || true
  exit 1
fi

"$PY" - <<'PYEOF'
import json
import sys

with open("/tmp/polymarket-live-data-response.json") as fh:
    data = json.load(fh)

if not isinstance(data, list) or not data:
    print(f"/api/v1/games/markets?tag_slug=wnba returned no markets: {data!r}", file=sys.stderr)
    sys.exit(1)

required = {"market_id", "question", "price_a", "price_b", "best_bid", "best_ask"}
missing = required - data[0].keys()
if missing:
    print(f"market response missing fields: {missing}", file=sys.stderr)
    sys.exit(1)

# A resolved/stale market settles to a 0/1 outcomePrice; the real "is this
# market actually open" signal is a genuine bid/ask spread (same convention
# as PolymarketService._is_relevant()).
live = [m for m in data if m.get("question") and 0.01 < (m["best_ask"] - m["best_bid"]) < 0.99]
if not live:
    print(f"/api/v1/games/markets?tag_slug=wnba returned {len(data)} markets, none with a live bid/ask spread", file=sys.stderr)
    sys.exit(1)

print(f"OK — endpoint returned {len(live)} live markets (of {len(data)} total), sample: {live[0]['question']!r}")
PYEOF

# ---------------------------------------------------------------------------
# 3. Frontend has a page/component that fetches the markets endpoint and
#    renders question + price, and the build succeeds (static checks only —
#    no browser automation this round).
# ---------------------------------------------------------------------------
echo "--- Checking frontend markets view (static) ---"

if ! grep -rlE "games/markets" frontend/src >/dev/null 2>&1; then
  echo "no frontend source file references the /games/markets endpoint" >&2
  exit 1
fi

MARKETS_FILE=$(grep -rlE "games/markets" frontend/src | head -1)

if ! grep -qE "question" "$MARKETS_FILE"; then
  echo "$MARKETS_FILE references the markets endpoint but never reads .question" >&2
  exit 1
fi
if ! grep -qE "price_a|price_b" "$MARKETS_FILE"; then
  echo "$MARKETS_FILE references the markets endpoint but never reads a price field" >&2
  exit 1
fi

( cd frontend && npm run build --silent ) || { echo "frontend build failed" >&2; exit 1; }

echo "--- ALL CHECKS PASSED ---"
