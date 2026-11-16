USE WHEN: about to "clean up," "fix," or "complete" code that looks
unfinished, placeholder, or unusual (TODOs, hardcoded stand-ins, stubs)
while working on an unrelated task.

## Pattern

Known placeholder/stand-in code in this repo is intentional and scoped to a
later phase, not an oversight — don't fix it as a drive-by while doing
unrelated work. If it looks in-scope for the current task, ask first rather
than assuming.

## Known instances

- `model_prob = 0.5` in `edge_engine.py` and the stub `find_prop_edges` —
  see [[decision-predictor-ml-integration]].
- `WNBA_SPORT` in `odds.py` (odds.py:19) — as of 2026-11, the NBA season is
  live and `NBA_SPORT` is the default everywhere (`get_nba_game_lines`,
  `get_nba_player_props`, `EdgeEngine.find_prop_edges`). `WNBA_SPORT` is kept
  as an explicit offseason fallback, not a default — pass it only when NBA
  markets are genuinely empty (summer). Both constants are now public (were
  `_NBA_SPORT`/`_WNBA_SPORT`) so callers can swap sport explicitly instead of
  the module silently picking one.
- `_NBA_API_SLEEP = 0.6` in `nba_data.py:25`, called before every `nba_api`
  request (8 call sites) — a deliberate rate-limit guard, not dead weight or
  an accidental slowdown. Don't remove it or shrink it to "optimize" latency;
  don't parallelize the calls it's meant to throttle.
- `TAG_WNBA` in `polymarket.py` (same purpose, alongside
  `get_nba_markets(tag_slug: str = TAG_NBA)`) — mirrors `WNBA_SPORT` above:
  NBA is live, so `TAG_NBA` is the default tag for the Markets page and the
  `/games/markets` endpoint. `TAG_WNBA` (was private `_TAG_WNBA`) is kept as
  an explicit offseason fallback only. Don't remove either constant or
  restrict `get_nba_markets` back to NBA-only.

## Why

Prevents an agent from treating scoped-out placeholder code as a bug and
burning a PR's scope on unplanned "fixes."
