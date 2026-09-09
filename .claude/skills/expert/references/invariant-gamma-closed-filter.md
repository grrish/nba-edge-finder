USE WHEN: querying Polymarket's Gamma API (`/events`) for "live"/"open"
markets, in `polymarket.py` or any new caller.

## Invariant

Gamma's `active=true` query param does **not** exclude resolved markets —
`active` and `closed` are independent flags, and a market can be
`active=true, closed=true` for months after it resolves. Querying with only
`active=true` silently returns stale/resolved markets alongside genuinely
live ones.

The bid/ask-spread heuristic (`_is_relevant()`'s `0.01 < ask - bid < 0.99`)
is **not** a reliable liveness signal by itself — some resolved markets never
fully converge their orderbook to exact 0/1 and pass the spread check anyway
(confirmed live 2026-09-09: WNBA markets closing 2024/2025 with genuine
spreads, e.g. "Will the Connecticut Sun win the 2024 WNBA Finals?").

Always pass `closed=false` alongside `active=true` in the Gamma `/events`
query (`polymarket.py`'s `_fetch_gamma_markets`) when the goal is genuinely
open markets. Don't rely on the spread heuristic, `close_time`/`endDate`
comparisons, or `active` alone to detect liveness — `closed` is the field
Gamma itself uses.

## Why

Discovered during `/evaluate-pr` for `polymarket-live-data`: the PRD's
`run-prd-test.sh` passed using the spread heuristic alone, but every "live"
market it found was actually a resolved market from a prior WNBA season.
`_fetch_gamma_markets` queried `active=true` only; adding `closed=false`
fixed it and surfaced real 2026 markets. See
[[pattern-dont-silently-fix-scaffolds]] for the `_TAG_WNBA` stand-in this
sits alongside.
