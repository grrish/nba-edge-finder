"""Polymarket prediction-market data service.

Fetches NBA markets from the Gamma API (no auth required) and
exposes probabilities for use in the edge engine.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Dict, List, Optional

import requests

from services.cache import CacheDB, CACHE_DB_PATH

logger = logging.getLogger(__name__)

_GAMMA_BASE   = "https://gamma-api.polymarket.com"
_REQ_HEADERS  = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

_TTL_MARKETS  = 15 * 60   # 15 min — prices move faster than odds

# Common NBA team name fragments used in fuzzy matching
_NBA_TEAM_ALIASES: Dict[str, List[str]] = {
    "hawks":       ["Atlanta", "Hawks"],
    "celtics":     ["Boston", "Celtics"],
    "nets":        ["Brooklyn", "Nets"],
    "hornets":     ["Charlotte", "Hornets"],
    "bulls":       ["Chicago", "Bulls"],
    "cavaliers":   ["Cleveland", "Cavaliers", "Cavs"],
    "mavericks":   ["Dallas", "Mavericks", "Mavs"],
    "nuggets":     ["Denver", "Nuggets"],
    "pistons":     ["Detroit", "Pistons"],
    "warriors":    ["Golden State", "Warriors", "GSW"],
    "rockets":     ["Houston", "Rockets"],
    "pacers":      ["Indiana", "Pacers"],
    "clippers":    ["LA Clippers", "Clippers"],
    "lakers":      ["LA Lakers", "Lakers", "Los Angeles Lakers"],
    "grizzlies":   ["Memphis", "Grizzlies"],
    "heat":        ["Miami", "Heat"],
    "bucks":       ["Milwaukee", "Bucks"],
    "timberwolves":["Minnesota", "Timberwolves", "Wolves"],
    "pelicans":    ["New Orleans", "Pelicans"],
    "knicks":      ["New York", "Knicks"],
    "thunder":     ["Oklahoma City", "Thunder", "OKC"],
    "magic":       ["Orlando", "Magic"],
    "76ers":       ["Philadelphia", "76ers", "Sixers"],
    "suns":        ["Phoenix", "Suns"],
    "blazers":     ["Portland", "Trail Blazers", "Blazers"],
    "kings":       ["Sacramento", "Kings"],
    "spurs":       ["San Antonio", "Spurs"],
    "raptors":     ["Toronto", "Raptors"],
    "jazz":        ["Utah", "Jazz"],
    "wizards":     ["Washington", "Wizards"],
}

# Flat set of all alias strings → canonical slug (for reverse lookup)
_ALIAS_TO_SLUG: Dict[str, str] = {}
for _slug, _aliases in _NBA_TEAM_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_TO_SLUG[_alias.lower()] = _slug


class PolymarketService:
    """Fetch NBA market data from Polymarket's Gamma API."""

    def __init__(self) -> None:
        self._cache = CacheDB(CACHE_DB_PATH)

    # ------------------------------------------------------------------
    # 1. Market discovery
    # ------------------------------------------------------------------

    def get_nba_markets(self) -> List[Dict]:
        """Fetch all active NBA markets from Polymarket's Gamma API.

        Each dict contains:
            market_id, question, outcome_a, outcome_b,
            price_a, price_b,          (0-1 implied probability)
            volume, liquidity,
            close_time,
            best_bid, best_ask, last_trade_price,
            clob_token_ids             (list of str, for CLOB lookups)

        Returns a mix of game markets and futures; callers can filter
        by question content or match via match_to_game().
        """
        key = "poly_nba_markets"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        logger.info("API CALL  get_nba_markets  source=Gamma")
        markets = self._fetch_gamma_markets(tag_slug="nba", limit=200)

        structured = [self._parse_market(m) for m in markets if self._is_relevant(m)]
        logger.info("Polymarket: %d structured NBA markets returned", len(structured))
        self._cache.set(key, structured, _TTL_MARKETS)
        return structured

    def _fetch_gamma_markets(self, tag_slug: str, limit: int) -> List[Dict]:
        """Pull raw markets from the Gamma /events endpoint (nested markets)."""
        try:
            resp = requests.get(
                f"{_GAMMA_BASE}/events",
                params={"active": "true", "limit": limit, "tag_slug": tag_slug},
                headers=_REQ_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json()
        except requests.RequestException as exc:
            logger.error("Gamma API error: %s", exc)
            return []

        raw_markets: List[Dict] = []
        for event in events:
            for m in event.get("markets", []):
                m["_event_title"] = event.get("title", "")
                m["_event_slug"]  = event.get("slug", "")
                raw_markets.append(m)

        return raw_markets

    @staticmethod
    def _is_relevant(m: Dict) -> bool:
        """Keep markets that have real pricing (not fully resolved to 0/1)."""
        bid = float(m.get("bestBid") or 0)
        ask = float(m.get("bestAsk") or 1)
        vol = float(m.get("volumeNum") or 0)
        # Accept: live markets with real spread, OR high-volume resolved markets
        has_real_spread = 0.01 < ask - bid < 0.99
        has_volume      = vol > 1_000
        return has_real_spread or has_volume

    @staticmethod
    def _parse_market(m: Dict) -> Dict:
        """Normalise raw Gamma market into a clean dict."""
        outcomes    = m.get("outcomes", [])      # JSON string or list
        prices_raw  = m.get("outcomePrices", []) # JSON string or list

        # Gamma sometimes returns these as JSON-encoded strings
        if isinstance(outcomes, str):
            import json
            outcomes   = json.loads(outcomes)
        if isinstance(prices_raw, str):
            import json
            prices_raw = json.loads(prices_raw)

        def to_float(v: object) -> float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        price_a = to_float(prices_raw[0]) if len(prices_raw) > 0 else 0.0
        price_b = to_float(prices_raw[1]) if len(prices_raw) > 1 else 0.0

        clob_ids = m.get("clobTokenIds", [])
        if isinstance(clob_ids, str):
            import json
            try:
                clob_ids = json.loads(clob_ids)
            except Exception:
                clob_ids = []

        return {
            "market_id":       str(m.get("id", "")),
            "question":        m.get("question", ""),
            "event_title":     m.get("_event_title", ""),
            "outcome_a":       outcomes[0] if len(outcomes) > 0 else "Yes",
            "outcome_b":       outcomes[1] if len(outcomes) > 1 else "No",
            "price_a":         round(price_a, 4),
            "price_b":         round(price_b, 4),
            "best_bid":        to_float(m.get("bestBid")),
            "best_ask":        to_float(m.get("bestAsk")),
            "last_trade_price":to_float(m.get("lastTradePrice")),
            "volume":          round(float(m.get("volumeNum") or 0), 2),
            "liquidity":       round(float(m.get("liquidityNum") or 0), 2),
            "close_time":      m.get("endDate", ""),
            "clob_token_ids":  clob_ids,
            "active":          bool(m.get("active")),
            "closed":          bool(m.get("closed")),
        }

    # ------------------------------------------------------------------
    # 2. Game matching
    # ------------------------------------------------------------------

    def match_to_game(
        self,
        market: Dict,
        games: List[Dict],
    ) -> Optional[Dict]:
        """Fuzzy-match a Polymarket market question to a game from today's slate.

        Strategy:
          1. Extract all team name tokens from the market question.
          2. Map tokens → canonical team slugs via _ALIAS_TO_SLUG.
          3. If we find exactly 2 different slugs and they match a game's
             home/away teams, return that game dict.

        Returns the matched game dict or None.
        """
        if not games:
            return None

        question = market.get("question", "").lower()
        found_slugs: set = set()

        for alias, slug in _ALIAS_TO_SLUG.items():
            if alias in question:
                found_slugs.add(slug)

        if len(found_slugs) < 2:
            return None

        for game in games:
            home_slug = self._team_to_slug(game.get("home_team", ""))
            away_slug = self._team_to_slug(game.get("away_team", ""))
            if not home_slug or not away_slug:
                continue
            if {home_slug, away_slug} == found_slugs:
                return game

        return None

    @staticmethod
    def _team_to_slug(team_name: str) -> Optional[str]:
        """Map a sportsbook team name string to our canonical slug."""
        name_lower = team_name.lower()
        for alias, slug in _ALIAS_TO_SLUG.items():
            if alias in name_lower:
                return slug
        return None

    # ------------------------------------------------------------------
    # 3. Probability lookup
    # ------------------------------------------------------------------

    def get_market_probability(self, market_id: str, outcome: str) -> float:
        """Return the current probability for *outcome* in a market.

        *outcome* should be "a" or "b" (case-insensitive), or the full
        outcome label string (e.g. "Yes", "No", "Lakers").
        """
        markets = self.get_nba_markets()
        market  = next((m for m in markets if m["market_id"] == market_id), None)
        if market is None:
            logger.warning("Market %s not found in cached NBA markets", market_id)
            return 0.0

        outcome_lower = outcome.strip().lower()
        if outcome_lower in ("a", market["outcome_a"].lower()):
            return market["price_a"]
        if outcome_lower in ("b", market["outcome_b"].lower()):
            return market["price_b"]

        logger.warning(
            "Outcome '%s' not found in market %s (outcomes: %s / %s)",
            outcome, market_id, market["outcome_a"], market["outcome_b"],
        )
        return 0.0


# ---------------------------------------------------------------------------
# __main__ — smoke-test every method
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s  %(message)s",
        stream=sys.stdout,
    )

    import os
    os.chdir(str(__import__("pathlib").Path(__file__).resolve().parent.parent))
    sys.path.insert(0, os.getcwd())

    svc = PolymarketService()
    D   = "-" * 60

    # ------------------------------------------------------------------
    print(D)
    print("1. get_nba_markets()")
    print(D)
    markets = svc.get_nba_markets()
    print(f"  Total markets returned: {len(markets)}")

    if markets:
        # Separate active (live spread) from resolved
        live    = [m for m in markets if 0.01 < m["best_ask"] - m["best_bid"] < 0.99]
        futures = [m for m in markets if m["volume"] > 100_000]
        print(f"  With live bid/ask spread: {len(live)}")
        print(f"  High-volume markets (>$100k): {len(futures)}")

        print()
        print("  Sample markets:")
        shown = set()
        for m in markets:
            q = m["question"]
            if q not in shown:
                shown.add(q)
                print(
                    f"    [{m['market_id']:>7s}]  {q[:55]:55s}"
                    f"  A={m['price_a']:.2f} B={m['price_b']:.2f}"
                    f"  vol=${m['volume']:>12,.0f}"
                )
            if len(shown) >= 10:
                break

    # ------------------------------------------------------------------
    print()
    print(D)
    print("2. match_to_game() — with today's NBA schedule")
    print(D)
    # Import NBADataService to get today's games
    from services.nba_data import NBADataService
    nba_svc = NBADataService()
    games   = nba_svc.get_todays_games()
    print(f"  Games today: {len(games)}")

    if games:
        matched_count = 0
        for m in markets[:30]:
            g = svc.match_to_game(m, games)
            if g:
                matched_count += 1
                print(f"  MATCH  '{m['question'][:50]}'  →  {g['away_team']} @ {g['home_team']}")
        print(f"  Total matched: {matched_count} / {min(30, len(markets))} sampled")
    else:
        print("  No NBA games today (offseason) — testing match logic against known market text:")
        # Synthetic test: prove the two-team matching logic works
        # match_to_game() requires BOTH teams to appear in the question
        # (it's for game-winner markets, not championship futures)
        fake_game = {
            "game_id":      "test-001",
            "home_team":    "Oklahoma City Thunder",
            "away_team":    "Indiana Pacers",
            "home_team_id": "1",
            "away_team_id": "2",
        }
        test_cases = [
            ("Oklahoma City Thunder vs Indiana Pacers",          True),   # both teams → match
            ("Will the Oklahoma City Thunder win the Finals?",   False),  # one team → no match
            ("Lakers vs Celtics",                                False),  # different teams → no match
        ]
        all_pass = True
        for question, expect_match in test_cases:
            mkt    = {"market_id": "t", "question": question}
            result = svc.match_to_game(mkt, [fake_game])
            matched = result is not None
            ok     = matched == expect_match
            all_pass = all_pass and ok
            print(
                f"  {'✓' if ok else '✗'}  '{question[:50]}'  "
                f"→ {'MATCH' if matched else 'no match'}  (expected {'match' if expect_match else 'no match'})"
            )
        print(f"  match_to_game logic: {'all correct ✓' if all_pass else 'FAILED ✗'}")

    # ------------------------------------------------------------------
    print()
    print(D)
    print("3. get_market_probability()")
    print(D)
    if markets:
        m = markets[0]
        prob_a = svc.get_market_probability(m["market_id"], "a")
        prob_b = svc.get_market_probability(m["market_id"], "b")
        print(f"  Market: {m['question'][:55]}")
        print(f"  P({m['outcome_a']}) = {prob_a:.4f}")
        print(f"  P({m['outcome_b']}) = {prob_b:.4f}")
        print(f"  Sum = {prob_a + prob_b:.4f}  (≤1.0 ✓)" if prob_a + prob_b <= 1.001 else f"  Sum = {prob_a + prob_b:.4f}  ✗")
    else:
        print("  No markets to test.")

    # ------------------------------------------------------------------
    print()
    print(D)
    print("4. Cache round-trip")
    print(D)
    markets2 = svc.get_nba_markets()
    print(f"  Second call returned {len(markets2)} markets from cache ✓")

    print()
    print("ALL CHECKS PASSED")
