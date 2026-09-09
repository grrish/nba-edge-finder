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
- `_WNBA_SPORT` in `odds.py` (used as a live stand-in for NBA odds during the
  offseason, odds.py:19) — deliberate scaffolding to sanity-check
  parsing/caching against live data when NBA markets are empty. Not leftover
  test code; don't remove it or restrict the service to NBA-only.
- `_NBA_API_SLEEP = 0.6` in `nba_data.py:25`, called before every `nba_api`
  request (8 call sites) — a deliberate rate-limit guard, not dead weight or
  an accidental slowdown. Don't remove it or shrink it to "optimize" latency;
  don't parallelize the calls it's meant to throttle.

## Why

Prevents an agent from treating scoped-out placeholder code as a bug and
burning a PR's scope on unplanned "fixes."
