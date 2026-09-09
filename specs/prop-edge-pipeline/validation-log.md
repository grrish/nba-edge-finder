# Validation Log: prop-edge-pipeline

Three parallel opus subagents independently reviewed `mainspec.md` +
`slices/1.1-*.md` + `slices/1.2-*.md` against the actual codebase (all three
ran `./prds/prop-edge-pipeline/run-prd-test.sh` directly and confirmed it
exits 0 today, 14 live WNBA edges). No project-specific `expert-*` skills
are registered (only the base `expert` skill) — the two relevant Expert
reference files (`decision-predictor-ml-integration.md`,
`pattern-dont-silently-fix-scaffolds.md`) were already read and cited by all
three subagents, so no separate expert-review pass surfaced new findings
beyond consensus.

## Subagent consensus

### 3/3 (Very High Confidence)

- **[Applied]** Slice 1.1 / "What to verify" — `find_prop_edges`'s per-game
  `except` handler re-subscripts `game["game_id"]` inside the log call
  (`edge_engine.py:170-174`); if the triggering `KeyError` came from that
  same subscript, the handler re-raises it and it escapes `find_prop_edges`
  uncaught — the exact "full-pipeline abort" the slice says can't happen.
  Fix applied: added an explicit "Known gap to fix" note instructing the
  implementer to bind `gid = game.get("game_id")` before the `try` and use
  it in both the fetch and log calls, mirroring `_score_game_edge`'s
  `game.get("id")` at `edge_engine.py:129`.

- **[Applied]** Slice 1.1 / Success Criteria — "the first two check blocks
  of `run-prd-test.sh` ... pass. Run the script and confirm" is not
  executable: the runner is one `set -euo pipefail` script with no block
  selector, and Slice 1.2 forbids modifying it. Fix applied: reworded the
  criterion to watch for the two success banners/OK-line in stdout before
  the live-data block starts, and explicitly hand off any later-block
  failure to Slice 1.2.

- **[Applied]** Slice 1.2 / "Live-data wiring" + Success Criteria —
  contradictory instructions: told to treat an empty `get_nba_game_lines`
  result as an environment problem ("don't fix it"), but Success Criteria
  still demands the runner exit 0 with no escape hatch, both changing the
  sport constant and editing the runner forbidden. Fix applied: added an
  explicit escape-hatch clause — report environment-blocked instead of
  treating it as an unmet criterion — in both the "Live-data wiring"
  section and the Success Criteria section.

- **[Applied]** Mainspec / "Important" section — Expert memory
  (`decision-predictor-ml-integration.md`,
  `pattern-dont-silently-fix-scaffolds.md`) still states `find_prop_edges`
  is a stub that must not be implemented, contradicting this PRD's premise.
  `AGENTS.md` instructs agents to trust the Expert for current reality, so
  an implementing agent that reads it hits a direct contradiction. Fix
  applied: added a note clarifying this PRD supersedes the
  "don't-implement" half of the clause, only the `model_prob = 0.5` half
  still binds, and `/learn` will reconcile the Expert files post-merge.

- **[Applied]** Both slices / Success Criteria — neither slice addresses
  that this repo has no unit-test framework (`AGENTS.md` requires asking
  first before adding one; no `pytest` in `backend/requirements.txt`),
  while `/implement-slice` mandates a unit-test step. Fix applied: added an
  explicit line to both slices stating the runner (fixture block for 1.1,
  full run for 1.2) is the test-equivalent, and prohibiting adding a test
  framework.

- **[Applied]** Mainspec / Forward-looking requirements — `find_prop_edges`
  permanently hardcodes `_WNBA_SPORT` while `GET /props/today` hardcodes
  NBA; once NBA season starts, `/api/v1/props/edges` silently returns `[]`
  again (behaviorally identical to the pre-feature stub), and both slices
  forbid touching the sport constant. The mainspec's claim that "nothing is
  expected to be extended" masked this as a non-issue. Fix applied: added
  an explicit "known, accepted, time-boxed limitation" bullet recording the
  risk without asking either slice to fix it (out of this PRD's scope).

### 2/3 (High Confidence)

- **[Applied]** Slice 1.2 / "HTTP wiring" — the mainspec and this slice's
  user story both mention the `player_id`-scoped
  `GET /api/v1/props/{player_id}/edges` route, but `run-prd-test.sh` only
  ever requests `/api/v1/props/edges`, and the slice declares the runner
  "authoritative ... not the descriptions above" — silently downgrading the
  scoped-route claim to unenforced prose. Fix applied: added a bullet
  requiring a separate (non-runner) check of the scoped route via
  `TestClient` or manual curl, clarified it doesn't block the PRD gate.

- **[Skipped: nitpick]** Mainspec / "What exists today" vs. Slice 1.1 —
  mainspec's restated Kelly formula drops the `if over_prob < 1 else 0.0`
  guard that slice 1.1 states correctly. Cosmetic drift between two
  documents describing the same already-correct code; doesn't change what
  an implementing agent would build.

- **[Skipped: nitpick]** Both slices — `_score_prop_edge`'s `market_prices`
  is always a single-element list (price-shopping already collapsed by
  `OddsService._parse_props`), so `best_source` isn't "best" across
  anything the way the game-edge path's is. True, but doesn't affect
  correctness of verification — nothing in either slice asks the
  implementer to compare across books.

### 1/3 (Discarded)

- Mainspec "Why" section overclaims `find_game_edges` as a working
  proof-of-wiring reference when it's actually equally broken
  (`get_game_odds`/`decimal_to_implied_prob` don't exist either) —
  discarded (low confidence, only one subagent flagged as a spec defect
  rather than a general observation).
- The under side of every prop (`under_prob`/`under_american`) is parsed
  but never scored, so the pipeline structurally only ever surfaces
  over-side opportunities — discarded (1/3; also arguably a PRD-scope
  question, not a spec-plan defect, since neither the PRD nor prior specs
  ever claimed both sides would be scored).
- 30-minute SQLite cache TTL means the "live wiring proof" block can pass
  purely from cache, without proving the live API path is reachable —
  discarded (1/3).
- Odds API quota fan-out (`1 + N` requests per scan) unbudgeted in the
  PRD/mainspec — discarded (all three subagents mentioned it, but
  explicitly as a "worth flagging" / "not a defect" note rather than a
  claimed spec defect; no subagent proposed it as something requiring a
  spec edit).

## Expert findings

No `expert-*` domain skills are registered for this project. The base
`expert` skill's reference files were already consulted by all three
subagents (see 3/3 finding on `decision-predictor-ml-integration.md` /
`pattern-dont-silently-fix-scaffolds.md` above); no additional
domain-specific findings surfaced beyond subagent consensus.

## Summary

- Total deduplicated findings: 12 (6 at 3/3, 3 at 2/3, 4 at 1/3, with one
  quota-fan-out item mentioned by all three but discarded as non-blocking)
- Impactful fixes applied: 7 (6 at 3/3, 1 at 2/3)
- Nitpicks skipped: 2 (both 2/3)
- Discarded (1/3 or non-blocking-by-consensus): 4
