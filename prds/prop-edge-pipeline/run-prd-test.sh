#!/usr/bin/env bash
# Definition of done for prop-edge-pipeline. The harness checks only the exit code.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

BACKEND_PORT="${PORT:-8098}"
PY="$REPO_ROOT/backend/venv/bin/python3"

# ---------------------------------------------------------------------------
# 1. Static guard: the ML placeholder is untouched — model_prob stays 0.5
#    and prop scoring never reaches for the real predictor.
# ---------------------------------------------------------------------------
echo "--- Checking ML placeholder is untouched ---"

if ! grep -q "model_prob: float = 0.5" backend/services/edge_engine.py; then
  echo "model_prob = 0.5 placeholder is missing from edge_engine.py" >&2
  exit 1
fi

if grep -qE "_score_prop_edge.*NBAPredictor|NBAPredictor.*_score_prop_edge" backend/services/edge_engine.py; then
  echo "_score_prop_edge appears to reach for NBAPredictor — real model must stay deferred" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 2 & 3. _score_prop_edge scoring math, and find_prop_edges' fetch → score →
#    filter → sort → player_id-filter pipeline, proven with fixture data so
#    the result doesn't depend on today's real market vig clearing the
#    threshold.
# ---------------------------------------------------------------------------
echo "--- Checking _score_prop_edge and find_prop_edges (fixture data) ---"

( cd backend && "$PY" - ) <<'PYEOF'
import asyncio
import sys

from services.edge_engine import EdgeEngine
from services.nba_data import NBADataService
from services.odds import OddsService
from services.polymarket import PolymarketService

engine = EdgeEngine(NBADataService(), OddsService(), PolymarketService())

# --- _score_prop_edge: losing edge (over_prob above model_prob=0.5) ---
losing_prop = {
    "game_id": "g1", "player_name": "Losing Player", "stat_type": "points",
    "line": 20.5, "over_american": -110, "under_american": -110,
    "over_prob": 0.5238, "under_prob": 0.5238, "bookmaker": "draftkings",
}
losing_edge = engine._score_prop_edge(losing_prop)
if losing_edge is None:
    print("_score_prop_edge returned None for a well-formed prop", file=sys.stderr)
    sys.exit(1)
if losing_edge.event_type != "prop":
    print(f"expected event_type='prop', got {losing_edge.event_type!r}", file=sys.stderr)
    sys.exit(1)
if losing_edge.model_probability != 0.5:
    print(f"expected model_probability=0.5, got {losing_edge.model_probability}", file=sys.stderr)
    sys.exit(1)
if abs(losing_edge.best_edge - (0.5 - 0.5238)) > 1e-6:
    print(f"expected best_edge≈-0.0238, got {losing_edge.best_edge}", file=sys.stderr)
    sys.exit(1)
if losing_edge.is_positive_ev:
    print("losing_prop (over_prob=0.5238) scored as positive EV — threshold logic is wrong", file=sys.stderr)
    sys.exit(1)

# --- _score_prop_edge: winning edge (over_prob well below model_prob=0.5) ---
winning_prop = {
    "game_id": "g1", "player_name": "Winning Player", "stat_type": "rebounds",
    "line": 8.5, "over_american": +150, "under_american": -180,
    "over_prob": 0.40, "under_prob": 0.60, "bookmaker": "fanduel",
}
winning_edge = engine._score_prop_edge(winning_prop)
if winning_edge is None or not winning_edge.is_positive_ev:
    print("winning_prop (over_prob=0.40) did not score as positive EV", file=sys.stderr)
    sys.exit(1)
if abs(winning_edge.best_edge - 0.10) > 1e-6:
    print(f"expected best_edge≈0.10, got {winning_edge.best_edge}", file=sys.stderr)
    sys.exit(1)
if winning_edge.best_source != "fanduel":
    print(f"expected best_source='fanduel', got {winning_edge.best_source!r}", file=sys.stderr)
    sys.exit(1)

# --- find_prop_edges: fetch → score → filter → sort → player_id filter ---
fixture_games = [{"game_id": "g1", "home_team": "A", "away_team": "B"}]
fixture_props = {
    "g1": [
        winning_prop,
        losing_prop,
        {  # a second, smaller winning edge — proves sort-descending
            "game_id": "g1", "player_name": "Winning Player", "stat_type": "assists",
            "line": 5.5, "over_american": +120, "under_american": -140,
            "over_prob": 0.45, "under_prob": 0.55, "bookmaker": "fanduel",
        },
    ]
}

engine._odds.get_nba_game_lines = lambda sport=None: fixture_games
engine._odds.get_nba_player_props = lambda game_id, sport=None: fixture_props[game_id]

edges = asyncio.run(engine.find_prop_edges())

if not isinstance(edges, list):
    print(f"find_prop_edges() returned {type(edges)}, expected a list", file=sys.stderr)
    sys.exit(1)
if len(edges) != 2:
    print(f"expected 2 positive-EV edges (losing_prop filtered out), got {len(edges)}", file=sys.stderr)
    sys.exit(1)
if not (edges[0].best_edge >= edges[1].best_edge):
    print("find_prop_edges() did not sort by best_edge descending", file=sys.stderr)
    sys.exit(1)
if edges[0].description.find("Winning Player") == -1 or "rebounds" not in edges[0].description:
    print(f"expected the largest edge to be Winning Player/rebounds, got {edges[0].description!r}", file=sys.stderr)
    sys.exit(1)

filtered = asyncio.run(engine.find_prop_edges(player_id="winning player"))
if len(filtered) != 2 or any("Losing Player" in e.description for e in filtered):
    print("player_id filter did not narrow to case-insensitive player_name match", file=sys.stderr)
    sys.exit(1)

print(f"OK — scoring math and pipeline wiring correct ({len(edges)} fixture edges, sorted, filter works)")
PYEOF

# ---------------------------------------------------------------------------
# 4. Live wiring proof: real OddsService calls (not the nonexistent
#    get_game_odds()/decimal_to_implied_prob() find_game_edges calls),
#    completing without error against today's live WNBA data.
# ---------------------------------------------------------------------------
echo "--- Checking find_prop_edges() against live WNBA data ---"

( cd backend && "$PY" - ) <<'PYEOF'
import asyncio
import sys

from services.edge_engine import EdgeEngine
from services.nba_data import NBADataService
from services.odds import OddsService
from services.polymarket import PolymarketService

odds = OddsService()
engine = EdgeEngine(NBADataService(), odds, PolymarketService())

# Prove the API key/live path is actually reachable before trusting an empty
# edges list as "nothing cleared the threshold" rather than "the call failed".
games = odds.get_nba_game_lines(sport="basketball_wnba")
if not games:
    print("get_nba_game_lines(sport='basketball_wnba') returned no live games — "
          "check ODDS_API_KEY in backend/.env or WNBA season state", file=sys.stderr)
    sys.exit(1)

try:
    edges = asyncio.run(engine.find_prop_edges())
except AttributeError as exc:
    print(f"find_prop_edges() called a nonexistent OddsService method: {exc}", file=sys.stderr)
    sys.exit(1)

if not isinstance(edges, list):
    print(f"find_prop_edges() returned {type(edges)} against live data, expected a list", file=sys.stderr)
    sys.exit(1)

for e in edges:
    if e.event_type != "prop" or not e.is_positive_ev or e.best_edge < 0.02:
        print(f"live edge failed invariants: {e}", file=sys.stderr)
        sys.exit(1)

print(f"OK — find_prop_edges() completed against live WNBA data, {len(edges)} edges cleared threshold")
PYEOF

# ---------------------------------------------------------------------------
# 5. GET /api/v1/props/edges is reachable and returns a well-formed
#    EdgeListResponse.
# ---------------------------------------------------------------------------
echo "--- Checking GET /api/v1/props/edges ---"

if curl -sf "http://localhost:${BACKEND_PORT}/health" >/dev/null 2>&1; then
  echo "port ${BACKEND_PORT} is already serving something (not started by this runner) — set PORT to a free port" >&2
  exit 1
fi

( cd backend && "$PY" -m uvicorn main:app --port "$BACKEND_PORT" >/tmp/prop-edge-pipeline-backend.log 2>&1 & )
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
  echo "backend never came up on :${BACKEND_PORT} — see /tmp/prop-edge-pipeline-backend.log" >&2
  cat /tmp/prop-edge-pipeline-backend.log >&2 || true
  exit 1
fi

http_code=$(curl -s -o /tmp/prop-edge-pipeline-response.json -w '%{http_code}' \
  "http://localhost:${BACKEND_PORT}/api/v1/props/edges")
if [[ "$http_code" != "200" ]]; then
  echo "GET /api/v1/props/edges returned $http_code, expected 200" >&2
  cat /tmp/prop-edge-pipeline-response.json >&2 || true
  exit 1
fi

"$PY" - <<'PYEOF'
import json
import sys

with open("/tmp/prop-edge-pipeline-response.json") as fh:
    data = json.load(fh)

required = {"edges", "generated_at", "total_opportunities"}
missing = required - data.keys()
if missing:
    print(f"/api/v1/props/edges response missing fields: {missing}", file=sys.stderr)
    sys.exit(1)
if not isinstance(data["edges"], list):
    print(f"/api/v1/props/edges 'edges' field is not a list: {type(data['edges'])}", file=sys.stderr)
    sys.exit(1)

print(f"OK — /api/v1/props/edges returned a well-formed EdgeListResponse ({data['total_opportunities']} opportunities)")
PYEOF

echo "--- ALL CHECKS PASSED ---"
