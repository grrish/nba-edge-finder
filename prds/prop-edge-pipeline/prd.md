# PRD: prop-edge-pipeline

## Why
`EdgeEngine.find_game_edges()` scans today's game lines and surfaces +EV
opportunities, but its prop-level sibling, `find_prop_edges()`, is a full
stub that always returns `[]` — the player-prop side of the edge finder
doesn't exist yet, even structurally. The developer wants the same
fetch → score → filter → sort pipeline that game edges already have, built
for props, so `/api/v1/props/edges` returns real data instead of an
unconditional empty list — using the `model_prob = 0.5` placeholder
(per the Expert's `decision-predictor-ml-integration` decision) since real
ML prediction is intentionally deferred.

## User story
As the developer, I can call `find_prop_edges()` (directly or via
`GET /api/v1/props/edges`) and get back real player-prop opportunities
scored against live sportsbook lines, so I know the prop pipeline is wired
correctly end-to-end — the same proof-of-wiring the game-edge path already
has, not just code that type-checks.

## Definition of done
`./prds/prop-edge-pipeline/run-prd-test.sh` exits 0:
- `EdgeEngine._score_prop_edge(prop)` builds an `EdgeScore` from a single
  OddsService prop dict (`event_type="prop"`, `model_probability=0.5`,
  `best_edge = model_prob - over_prob`, Kelly fraction and
  `is_positive_ev` computed the same way `_score_game_edge` computes them),
  verified against both a losing-edge and a winning-edge synthetic prop.
- `EdgeEngine.find_prop_edges()` no longer unconditionally returns `[]`: it
  fetches today's game slate and each game's player props from
  `OddsService` (using its real method names —
  `get_nba_game_lines`/`get_nba_player_props` — not the nonexistent
  `get_game_odds`/`decimal_to_implied_prob` that `find_game_edges` calls),
  scores every prop, keeps only `is_positive_ev` results, and returns them
  sorted by `best_edge` descending — proven with fixture data that includes
  a guaranteed-positive-edge prop and a guaranteed-negative-edge prop.
- The optional `player_id` filter narrows results to props whose
  `player_name` matches (case-insensitive) — there's no player-ID-to-name
  mapping in the odds pipeline today, so this is a name match, not a real
  NBA player ID lookup.
- Calling `find_prop_edges()` against live WNBA data (this project's
  existing in-season stand-in for NBA odds, per `odds.py`'s `_WNBA_SPORT`)
  completes without error and returns a list of well-formed `EdgeScore`
  objects — proving the live wiring is correct, independent of whether any
  real prop happens to clear the `_MIN_EDGE_THRESHOLD` today.
- `GET /api/v1/props/edges` is reachable over HTTP and returns 200 with a
  body matching `EdgeListResponse` (`edges`, `generated_at`,
  `total_opportunities`).
- The ML placeholder stays untouched: `model_prob = 0.5` is still present
  verbatim, and neither `find_prop_edges` nor `_score_prop_edge` imports or
  calls `NBAPredictor`.

## Out of scope
- Real ML prediction — `model_prob = 0.5` stays exactly as `_score_game_edge`
  uses it. Per `decision-predictor-ml-integration`, wiring the trained
  predictor in is a separate, later, explicitly-requested piece of work.
- Fixing `find_game_edges`/`_score_game_edge`'s existing bug (it calls
  `OddsService.get_game_odds()`/`decimal_to_implied_prob()`, neither of
  which exist). Pre-existing, unrelated to props — noted here so it isn't
  lost, not fixed in this PRD.
- Matching player props to Polymarket markets. `find_game_edges` doesn't
  actually score against Polymarket either (it's injected but unused) —
  props mirror that: `PolymarketService` isn't touched. There's also no
  existing player+stat+line matcher against Gamma markets, and Polymarket's
  NBA/WNBA tag markets are mostly game-winner/futures, not player props.
- Real NBA-player-ID resolution for the `player_id` filter (name match only,
  see above).
- Frontend changes — this PRD is backend pipeline only.

## Constraints
- Mirror `find_game_edges`'s shape: try/except around each fetch,
  `_MIN_EDGE_THRESHOLD` filter, `edges.sort(key=..., reverse=True)` before
  returning.
- Use `OddsService`'s real, current method signatures
  (`get_nba_game_lines(sport=...)`, `get_nba_player_props(game_id, sport=...)`)
  — not the broken calls `_score_game_edge` makes.
- New backend code follows existing conventions: response/request shapes are
  the existing `EdgeScore`/`EdgeListResponse` Pydantic models
  (`backend/models/schemas.py`), no inline dicts crossing the router
  boundary.
- No new dependencies.
