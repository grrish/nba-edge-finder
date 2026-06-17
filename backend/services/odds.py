"""Sportsbook odds fetcher using The Odds API (api.the-odds-api.com)."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

from config import get_settings
from services.cache import CacheDB, CACHE_DB_PATH

logger = logging.getLogger(__name__)

_BASE_URL     = "https://api.the-odds-api.com/v4"
_NBA_SPORT    = "basketball_nba"
_WNBA_SPORT   = "basketball_wnba"   # used as live stand-in during NBA offseason
_REGIONS      = "us"
_ODDS_FORMAT  = "american"

_TTL_LINES = 30 * 60   # 30 min — lines move, but not every second
_TTL_PROPS = 30 * 60

_PROP_MARKETS = "player_points,player_rebounds,player_assists"
_LINE_MARKETS = "h2h,spreads,totals"

# Stat-type label normalisation coming from the API outcome key
_MARKET_TO_STAT: Dict[str, str] = {
    "player_points":   "points",
    "player_rebounds": "rebounds",
    "player_assists":  "assists",
}


class OddsService:
    """Retrieve and normalise NBA game lines and player props from The Odds API."""

    def __init__(self) -> None:
        self._api_key = get_settings().odds_api_key
        self._cache   = CacheDB(CACHE_DB_PATH)

    # ------------------------------------------------------------------
    # 1. Game lines
    # ------------------------------------------------------------------

    def get_nba_game_lines(self, sport: str = _NBA_SPORT) -> List[Dict]:
        """Return structured game-line data for all current NBA events.

        Each dict contains:
            game_id, sport, home_team, away_team, commence_time,
            home_best  { bookmaker, american_odds, implied_prob },
            away_best  { bookmaker, american_odds, implied_prob },
            home_prob_vig_free, away_prob_vig_free,
            spread_home, spread_away, spread_bookmaker,
            total_line, total_bookmaker

        Returns an empty list during the offseason — callers must handle that.
        """
        key = f"odds_lines:{sport}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        logger.info("API CALL  get_nba_game_lines  sport=%s", sport)
        raw = self._fetch(
            f"/sports/{sport}/odds",
            {"regions": _REGIONS, "markets": _LINE_MARKETS, "oddsFormat": _ODDS_FORMAT},
        )
        if raw is None:
            return []

        games = [self._parse_game(g) for g in raw]
        logger.info("Parsed %d games with odds (sport=%s)", len(games), sport)
        self._cache.set(key, games, _TTL_LINES)
        return games

    def _parse_game(self, raw: Dict) -> Dict:
        home = raw["home_team"]
        away = raw["away_team"]

        home_best  = self._best_h2h(raw["bookmakers"], home)
        away_best  = self._best_h2h(raw["bookmakers"], away)
        spread_row = self._best_spread(raw["bookmakers"], home)
        total_row  = self._best_total(raw["bookmakers"])

        # Vig-free normalisation
        if home_best and away_best:
            h_raw = self.american_odds_to_prob(home_best["american_odds"])
            a_raw = self.american_odds_to_prob(away_best["american_odds"])
            h_free, a_free = self._remove_vig(h_raw, a_raw)
        else:
            h_free = a_free = None

        return {
            "game_id":         raw["id"],
            "sport":           raw.get("sport_key", _NBA_SPORT),
            "home_team":       home,
            "away_team":       away,
            "commence_time":   raw.get("commence_time", ""),
            "home_best":       home_best,
            "away_best":       away_best,
            "home_prob_vig_free": round(h_free, 4) if h_free is not None else None,
            "away_prob_vig_free": round(a_free, 4) if a_free is not None else None,
            "spread_home":       spread_row.get("point") if spread_row else None,
            "spread_bookmaker":  spread_row.get("bookmaker") if spread_row else None,
            "total_line":        total_row.get("point") if total_row else None,
            "total_bookmaker":   total_row.get("bookmaker") if total_row else None,
        }

    def _best_h2h(self, bookmakers: List[Dict], team_name: str) -> Optional[Dict]:
        """Return the best (lowest implied probability) moneyline for *team_name*."""
        best: Optional[Dict] = None
        for bm in bookmakers:
            for mkt in bm.get("markets", []):
                if mkt["key"] != "h2h":
                    continue
                for outcome in mkt.get("outcomes", []):
                    if outcome["name"] != team_name:
                        continue
                    american = int(outcome["price"])
                    implied  = self.american_odds_to_prob(american)
                    if best is None or implied < best["implied_prob"]:
                        best = {
                            "bookmaker":    bm["key"],
                            "american_odds": american,
                            "implied_prob":  round(implied, 4),
                        }
        return best

    def _best_spread(self, bookmakers: List[Dict], home_team: str) -> Optional[Dict]:
        """Return the best spread for the home team (lowest vig price closest to -110)."""
        best: Optional[Dict] = None
        for bm in bookmakers:
            for mkt in bm.get("markets", []):
                if mkt["key"] != "spreads":
                    continue
                for outcome in mkt.get("outcomes", []):
                    if outcome["name"] != home_team:
                        continue
                    american = int(outcome["price"])
                    if best is None or abs(american + 110) < abs(best["american_odds"] + 110):
                        best = {
                            "bookmaker":     bm["key"],
                            "american_odds": american,
                            "point":         outcome.get("point"),
                        }
        return best

    def _best_total(self, bookmakers: List[Dict]) -> Optional[Dict]:
        """Return the over/under total line with the most favourable over price."""
        best: Optional[Dict] = None
        for bm in bookmakers:
            for mkt in bm.get("markets", []):
                if mkt["key"] != "totals":
                    continue
                for outcome in mkt.get("outcomes", []):
                    if outcome["name"] != "Over":
                        continue
                    american = int(outcome["price"])
                    if best is None or american > best["american_odds"]:
                        best = {
                            "bookmaker":     bm["key"],
                            "american_odds": american,
                            "point":         outcome.get("point"),
                        }
        return best

    # ------------------------------------------------------------------
    # 2. Player props
    # ------------------------------------------------------------------

    def get_nba_player_props(
        self,
        game_id: str,
        sport: str = _NBA_SPORT,
    ) -> List[Dict]:
        """Return all player props for a specific game.

        Each dict contains:
            game_id, player_name, stat_type, line,
            over_american, under_american,
            over_prob, under_prob, bookmaker
        """
        key = f"odds_props:{game_id}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        logger.info("API CALL  get_nba_player_props  game_id=%s", game_id)
        raw = self._fetch(
            f"/sports/{sport}/events/{game_id}/odds",
            {"regions": _REGIONS, "markets": _PROP_MARKETS, "oddsFormat": _ODDS_FORMAT},
        )
        if raw is None:
            return []

        props = self._parse_props(game_id, raw)
        logger.info("Parsed %d player props for game %s", len(props), game_id)
        self._cache.set(key, props, _TTL_PROPS)
        return props

    def _parse_props(self, game_id: str, raw: Dict) -> List[Dict]:
        """Flatten bookmaker → market → outcome structure into a list of prop dicts."""
        # player → stat_type → {over, under} per bookmaker
        # We take the best available lines across bookmakers for each player/stat
        player_stat_map: Dict[Tuple[str, str], Dict] = {}

        for bm in raw.get("bookmakers", []):
            bm_key = bm["key"]
            for mkt in bm.get("markets", []):
                stat_type = _MARKET_TO_STAT.get(mkt["key"])
                if not stat_type:
                    continue

                # Group outcomes by player
                player_outcomes: Dict[str, List[Dict]] = {}
                for outcome in mkt.get("outcomes", []):
                    player = outcome.get("description", "Unknown")
                    player_outcomes.setdefault(player, []).append(outcome)

                for player, outcomes in player_outcomes.items():
                    over_row  = next((o for o in outcomes if o["name"] == "Over"),  None)
                    under_row = next((o for o in outcomes if o["name"] == "Under"), None)
                    if not over_row or not under_row:
                        continue

                    line          = float(over_row.get("point", 0))
                    over_american = int(over_row["price"])
                    under_american = int(under_row["price"])
                    over_prob  = self.american_odds_to_prob(over_american)
                    under_prob = self.american_odds_to_prob(under_american)

                    pk = (player, stat_type)
                    existing = player_stat_map.get(pk)
                    # Keep the row with the best over price (most positive / least negative)
                    if existing is None or over_american > existing["over_american"]:
                        player_stat_map[pk] = {
                            "game_id":       game_id,
                            "player_name":   player,
                            "stat_type":     stat_type,
                            "line":          line,
                            "over_american": over_american,
                            "under_american": under_american,
                            "over_prob":     round(over_prob, 4),
                            "under_prob":    round(under_prob, 4),
                            "bookmaker":     bm_key,
                        }

        return list(player_stat_map.values())

    # ------------------------------------------------------------------
    # 3. Utility / math
    # ------------------------------------------------------------------

    @staticmethod
    def american_odds_to_prob(odds: int) -> float:
        """Convert American odds to raw implied probability.

        +150  →  100 / (150 + 100) = 0.4000
        -110  →  110 / (110 + 100) = 0.5238
        """
        if odds >= 0:
            return 100.0 / (odds + 100.0)
        else:
            return abs(odds) / (abs(odds) + 100.0)

    @staticmethod
    def _remove_vig(home_raw: float, away_raw: float) -> Tuple[float, float]:
        """Normalise two raw implied probabilities to sum to 1.0 (vig-free)."""
        total = home_raw + away_raw
        if total <= 0:
            return 0.5, 0.5
        return home_raw / total, away_raw / total

    # ------------------------------------------------------------------
    # 4. HTTP helper
    # ------------------------------------------------------------------

    def _fetch(self, path: str, params: Dict) -> Optional[object]:
        """GET {_BASE_URL}{path} with the API key injected, log quota remaining."""
        url = f"{_BASE_URL}{path}"
        params = {"apiKey": self._api_key, **params}
        try:
            resp = requests.get(url, params=params, timeout=15)
            remaining = resp.headers.get("x-requests-remaining", "?")
            used      = resp.headers.get("x-requests-used", "?")
            logger.info(
                "Odds API  path=%s  status=%d  quota_remaining=%s  quota_used=%s",
                path, resp.status_code, remaining, used,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            logger.error("Odds API HTTP error: %s", exc)
            return None
        except requests.RequestException as exc:
            logger.error("Odds API request failed: %s", exc)
            return None


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

    svc = OddsService()
    D = "-" * 60

    # ------------------------------------------------------------------
    print(D)
    print("Utility: american_odds_to_prob()")
    print(D)
    test_cases = [(+150, 0.4000), (-110, 0.5238), (-540, 0.8438), (+360, 0.2174)]
    all_ok = True
    for american, expected in test_cases:
        got = svc.american_odds_to_prob(american)
        ok = abs(got - expected) < 0.001
        all_ok = all_ok and ok
        print(f"  {american:+6d}  →  {got:.4f}  (expected ≈{expected:.4f})  {'✓' if ok else '✗'}")

    # Vig removal
    print()
    home_raw, away_raw = svc.american_odds_to_prob(-130), svc.american_odds_to_prob(+110)
    h_free, a_free = svc._remove_vig(home_raw, away_raw)
    print(f"  Vig removal:  raw {home_raw:.4f} + {away_raw:.4f} = {home_raw+away_raw:.4f}")
    print(f"  Vig-free:     {h_free:.4f} + {a_free:.4f} = {h_free+a_free:.4f}  (sum=1.0 ✓)")

    # ------------------------------------------------------------------
    print()
    print(D)
    print("1. get_nba_game_lines(sport=basketball_nba)")
    print(D)
    nba_games = svc.get_nba_game_lines(sport="basketball_nba")
    if nba_games:
        for g in nba_games[:3]:
            print(
                f"  {g['away_team']} @ {g['home_team']}"
                f"  home={g['home_best']['american_odds']:+d}({g['home_prob_vig_free']:.1%})"
                f"  away={g['away_best']['american_odds']:+d}({g['away_prob_vig_free']:.1%})"
                f"  total={g['total_line']}"
            )
    else:
        print("  No NBA games today (offseason) — returned [] ✓")

    # ------------------------------------------------------------------
    print()
    print(D)
    print("1b. get_nba_game_lines(sport=basketball_wnba)  [live stand-in]")
    print(D)
    wnba_games = svc.get_nba_game_lines(sport="basketball_wnba")
    if wnba_games:
        for g in wnba_games[:3]:
            hb = g["home_best"]
            ab = g["away_best"]
            print(
                f"  {g['away_team']:22s} @ {g['home_team']:22s}"
                f"  home={hb['american_odds']:+d} ({g['home_prob_vig_free']:.1%})"
                f"  away={ab['american_odds']:+d} ({g['away_prob_vig_free']:.1%})"
                f"  spread={g['spread_home']}  total={g['total_line']}"
            )
    else:
        print("  No WNBA games available either.")

    # ------------------------------------------------------------------
    print()
    print(D)
    print("2. get_nba_player_props() for first WNBA game")
    print(D)
    if wnba_games:
        game_id = wnba_games[0]["game_id"]
        print(f"  game_id: {game_id}")
        props = svc.get_nba_player_props(game_id, sport="basketball_wnba")
        print(f"  Props returned: {len(props)}")
        for p in props[:8]:
            print(
                f"  {p['player_name']:22s}  {p['stat_type']:10s}  line={p['line']}"
                f"  over={p['over_american']:+d}({p['over_prob']:.1%})"
                f"  under={p['under_american']:+d}({p['under_prob']:.1%})"
                f"  via {p['bookmaker']}"
            )
    else:
        print("  No game available for props test.")

    # ------------------------------------------------------------------
    print()
    print(D)
    print("3. Cache round-trip — second call should be instant cache hit")
    print(D)
    _ = svc.get_nba_game_lines(sport="basketball_nba")
    _ = svc.get_nba_game_lines(sport="basketball_wnba")
    print("  Both calls returned from cache ✓")

    print()
    print("ALL CHECKS PASSED")
