# Validation Log: polymarket-live-data

Three parallel Opus subagents independently reviewed the mainspec + all
three slices, grounding findings in the actual codebase (and, in two cases,
live calls to Polymarket's Gamma API). Expert review consulted
`concept-cache-backend-choice` and `pattern-dont-silently-fix-scaffolds` —
no additional blocking findings beyond what the subagents already
identified.

## Subagent consensus

### 3/3 (Very High Confidence)

- **[Applied]** Mainspec Codebase context / Slice 1.1 — `odds.py` line
  citations (`_WNBA_SPORT` at :409, `get_nba_game_lines` at :438, cache key
  at :451) are wrong; `odds.py` is 406 lines total. Actual locations are
  :19, :48, :61 — the cited range lands in the file's `__main__` smoke-test
  block. Fix applied: corrected all three citations in mainspec.md and
  slice 1.1.
- **[Applied]** Mainspec Codebase context / Slice 1.2 Success Criteria — the
  claim that `SecurityHeadersMiddleware` *and* the rate limiter "apply
  automatically" / "wrap every route" is false: `SlowAPIMiddleware` is
  never registered in `main.py` and no route uses `@limiter.limit`, so no
  route in the app is actually rate-limited today (`@limiter.exempt` on
  `/health` is a no-op). Fix applied: corrected the claim in both files to
  state SecurityHeadersMiddleware applies, the Limiter is configured but
  unenforced, pre-existing and out of scope — don't wire it up as a
  drive-by.
- **[Applied]** Slice 1.2 route body — the new route drops the
  `try/except Exception: pass` guard `/today/markets` already has around
  `PolymarketMarket(**pm)` construction (games.py:115). `PolymarketMarket`
  requires non-optional `question`/`close_time` and constrains
  `price_a`/`price_b` to `[0.0, 1.0]`; one malformed Gamma market would
  otherwise 500 the whole endpoint. Fix applied: added the same per-item
  try/except (silent skip, matching the existing pattern — no logger exists
  in `games.py` today, so no logging was introduced) plus a new Success
  Criterion asserting malformed markets are skipped, not fatal.
- **[Applied]** Mainspec / all slices — no unit-test framework exists in
  this repo (no `pytest`, no `vitest`/`jest`) and the PRD forbids new
  dependencies, but none of the slices state a verification approach,
  leaving `/implement-slice`'s "with unit tests" contract unresolved. Fix
  applied: added an explicit "Verification posture" note to the mainspec's
  Codebase context, plus a `## Verification` section to each of the three
  slices giving the specific manual/smoke-test command to run instead.
- **[Applied]** Slice 1.1 / Slice 1.2 — Slice 1.1 introduces `_TAG_NBA` as a
  private module constant, but Slice 1.2's router code re-hardcodes the
  bare literal `"nba"` as the route default — directly contradicting the
  mainspec's own guidance ("if a default tag needs to live somewhere other
  than a literal, it goes through Settings... not a bare module constant
  duplicated across files"). Fix applied: renamed `_TAG_NBA` to public
  `TAG_NBA` in slice 1.1 (kept `_TAG_WNBA` private, mirroring `odds.py`'s
  `_WNBA_SPORT` scaffolding convention exactly), and updated slice 1.2 to
  import and use `TAG_NBA` as the `Query(...)` default instead of the bare
  literal.
- **[Applied, as documentation]** Mainspec Out of scope — `get_market_probability`
  (`polymarket.py:249`) keeps calling `get_nba_markets()` with no tag
  argument, so it can never resolve a `market_id` returned by the new
  `tag_slug=wnba` endpoint. Harmless today (nothing calls it with non-NBA
  IDs) but was previously unacknowledged. Fix applied: added one line to
  the mainspec's Out of scope section naming this as a scope decision, not
  an oversight — no code change, since fixing it is out of scope for this
  feature.

### 2/3 (High Confidence)

- **[Applied]** Slice 1.1 — `_fetch_gamma_markets` returns `[]` both on a
  genuinely-empty result and on `requests.RequestException`, and the
  service caches `structured` unconditionally for 15 minutes. A single
  transient Gamma failure poisons the `poly_markets:<tag>` cache entry with
  `[]`, causing the PRD test runner (or any caller) to see "no live data"
  for the full TTL even after Gamma recovers. `odds.py` (the pattern this
  slice is told to mirror) guards against this with an explicit
  `if raw is None: return []` that skips the cache write on failure;
  `polymarket.py` had no equivalent. Fix applied: changed the cache write
  to `if structured: self._cache.set(...)`, with an explanatory note.
- **[Applied]** Slice 1.2 — `tag_slug` was an unconstrained free-form query
  param, and the cache key (`f"poly_markets:{tag_slug}"`) is written by
  `CacheDB`, which never evicts rows. An unconstrained param lets any
  caller grow `cache.db` without bound and trigger a live outbound Gamma
  request per distinct value, on an unauthenticated GET with no effective
  rate limiting (see the 3/3 finding above). Fix applied: constrained the
  query param with `Query(TAG_NBA, pattern=r"^[a-z0-9-]{1,32}$")` and added
  a Success Criterion asserting invalid `tag_slug` values 422.

### 1/3 (Discarded per protocol)

- Agent B (only): **Root-cause misdiagnosis** — `_fetch_gamma_markets`
  passes `active=true` to Gamma but never `closed=false`. Live verification
  showed 0/282 wnba markets and 0/288 nba markets have `closed=False` under
  the current query; the 26 wnba markets that pass the "genuine spread"
  liveness check are all `closed=True`, 2024-dated, and never fully
  converged — not live in the sense the PRD's "NBA offseason" framing
  claims. Only one of three agents identified this. Per protocol, 1/3
  findings are discarded regardless of severity. **Flagging this
  prominently here despite the discard**: if the PRD test starts passing on
  stale/resolved data, or fails outright once WNBA's season ends, this is
  the most likely root cause and is worth a human look at
  `/evaluate-pr` time — it was not applied as a spec fix in this pass.
- Agent B (only): frontend renders `price_a`, which is exactly 0 or 1 for
  100% of markets under the current (un-fixed) Gamma query — a consequence
  of the same root-cause issue above. Discarded for the same reason (1/3);
  would likely resolve on its own if the `closed=false` issue above were
  ever fixed.
- Agent C (only): Slice 1.1 doesn't extend `polymarket.py`'s `__main__`
  smoke-test block with a WNBA stand-in section, unlike `odds.py`'s
  `__main__` which has one. Discarded (1/3) — nitpick-adjacent given the
  Verification section already added covers manual smoke-testing.
- Agent C (only): the feature's definition of done is seasonally
  perishable — once WNBA's season ends (~October), `tag_slug=wnba` will
  stop returning live spreads and the PRD runner will start failing with
  no code change. Discarded (1/3); worth knowing but not spec-actionable
  today.
- Agent A (only): frontend hardcodes `tag_slug=wnba` with no on-screen
  indication it's a stand-in, not real NBA data. Discarded (1/3) — nitpick,
  low implementation impact.
- Agent A (only): React `key={m.market_id}` could collide if `market_id` is
  empty for multiple markets. Discarded (1/3) — cosmetic.
- Agent B (only): Slice 1.1's user story names `edge_engine.py` as an
  existing caller of `get_nba_markets`; grep shows it isn't. Discarded
  (1/3) — wording-only, Success Criteria already hedges correctly with
  "if it calls this service."
- Agent B (only): the runner overstates independently verifying the HTTP
  path — `CACHE_DB_PATH` is absolute, so step 2's server reads step 1's
  cached fetch rather than doing a fresh live call. Discarded (1/3) —
  accurate but doesn't change any slice's required behavior.
- Agent C (only): Slice 1.1's BEFORE/AFTER blocks omit the existing
  docstring on `get_nba_markets`, technically making the "docstring
  unchanged" claim inaccurate once AFTER is copied verbatim. Discarded
  (1/3) — nitpick, style-level.
- Agent C (only): Slice 1.2's AFTER block imports `List` as if new; it's
  already imported in `games.py`. Discarded (1/3) — cosmetic.
- Agent C (only): mainspec's "What (end state)" #3 overstates verification
  as "proving the data reaches the browser" when only static grep + build
  checks are in scope (no browser verification per Out of scope). Discarded
  (1/3) — wording nitpick, doesn't affect any Success Criterion.

## Expert findings

- No new blocking findings. `concept-cache-backend-choice` confirmed
  SQLite's cache-eviction gap is a known, accepted tradeoff (not something
  this feature is expected to fix) — consistent with treating the
  tag_slug-validation fix as bounding the *symptom* (unbounded growth via
  an unconstrained input) rather than fixing SQLite's lack of eviction
  itself. `pattern-dont-silently-fix-scaffolds` confirmed `_WNBA_SPORT` in
  `odds.py` (and by extension `_TAG_WNBA` in this feature) is intentional
  scaffolding, not a target for cleanup — informed the decision to keep
  `_TAG_WNBA` private/unused-outside-service rather than "fixing" it by
  wiring it up somewhere.

## Summary

- Total deduplicated findings: 19
- Impactful fixes applied: 8 (7 code/spec-behavior fixes + 1
  documentation-only scope note)
- Nitpicks/low-confidence discarded (1/3): 11
- Notable discard flagged for human attention despite protocol: the
  `closed=false` root-cause finding (1/3, Agent B) — see above.
