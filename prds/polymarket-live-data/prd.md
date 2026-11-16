# PRD: polymarket-live-data

## Why
The Polymarket integration (`backend/services/polymarket.py`) and its
`/games/today/markets` endpoint exist, but nobody has confirmed they actually
carry real, live market data end-to-end — and nothing in the frontend shows
this data at all. It's currently the NBA offseason, so the NBA-tagged
Polymarket markets are stale/finished, not live. The developer wants proof —
not just code that compiles — that a real market with a real price can be
fetched from Polymarket and shown in the app, using WNBA (which has live
markets right now) as a stand-in the same way `odds.py` already does for
sportsbook lines.

## User story
As the developer, I can request real, live Polymarket market data for a
currently-live sport (WNBA, standing in for NBA during the offseason) through
the backend API, and see that data rendered in the frontend, so I know the
data pipeline genuinely works end-to-end instead of returning empty or stale
placeholders.

## Definition of done
`./prds/polymarket-live-data/run-prd-test.sh` exits 0:
- `PolymarketService.get_nba_markets()` accepts a sport/tag parameter instead
  of a hardcoded `"nba"` tag_slug, so a caller can request a different sport's
  markets without touching the service's internals — mirroring how
  `OddsService.get_nba_game_lines(sport=...)` already does this.
- Calling the service with a live sport (`tag_slug="wnba"`) returns markets
  that are demonstrably different from calling it with `"nba"` (proving the
  parameter is actually wired through, not accepted and ignored), including
  at least one market with a genuine open bid/ask spread — Polymarket's
  `outcomePrices` round to exactly 0/1 even on still-open markets, so a real
  bid/ask spread (the same signal `PolymarketService._is_relevant()` already
  uses) is what actually distinguishes a live market from a resolved one.
- A `GET` endpoint (`/api/v1/games/markets`) is reachable over HTTP, accepts
  the same tag/sport parameter, and returns real market data — including at
  least one market with a genuine bid/ask spread — independent of whether
  there's a matching scheduled game, so it still surfaces data when the NBA
  schedule itself is empty.
- The frontend builds successfully and contains a page/component that fetches
  from this endpoint and renders each returned market's question and price.

## Out of scope
- Full multi-sport support: no sport-selector UI, no config-driven sport
  list, no per-sport team-alias tables. Only the one tag/sport parameter
  needed to point at WNBA instead of NBA.
- Automatic runtime fallback (e.g. detecting empty NBA results and silently
  switching to WNBA in existing routes). This feature adds the *capability*
  to request a different sport; it does not change default behavior anywhere.
- Wiring the ML predictor placeholder (`model_prob = 0.5` in
  `edge_engine.py`) or implementing `find_prop_edges` — both are explicitly
  deferred per the Expert's `decision-predictor-ml-integration`.
- Game-matching (`match_to_game`) for non-NBA sports — the team-alias table
  stays NBA-only; the new endpoint returns raw markets, not matched games.
- Browser-based / visual verification of the frontend. Verified via build
  success and static checks only (no Playwright or similar added this
  round); visual confirmation happens by hand during `/evaluate-pr`.

## Constraints
- No new dependencies — Polymarket's Gamma API needs no auth/key, and no
  testing library is added to the frontend this round.
- New backend code follows existing conventions: the new route lives in
  `backend/routers/games.py`, reuses the existing `PolymarketMarket` schema
  (`backend/models/schemas.py`), and goes through `Settings`
  (`backend/config.py`) rather than bare hardcoded values where config is
  needed.
- `SecurityHeadersMiddleware` and the rate limiter already wrap every route
  (`backend/main.py`) — the new endpoint gets them for free, don't bypass.
- Leave `edge_engine.py`'s ML placeholder and `find_prop_edges` stub
  untouched (see `decision-predictor-ml-integration`).
- Mirror `odds.py`'s existing sport-parameterization pattern (a
  default-valued parameter) — don't introduce a new sport-config
  abstraction.
