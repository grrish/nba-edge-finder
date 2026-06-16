"""Sportsbook odds fetcher using the Odds API."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.the-odds-api.com/v4"
_NBA_SPORT_KEY = "basketball_nba"


class OddsService:
    """Retrieve moneyline and player-prop odds from the Odds API."""

    def __init__(self) -> None:
        self._api_key = get_settings().odds_api_key

    # ------------------------------------------------------------------
    # Game moneylines
    # ------------------------------------------------------------------

    def get_game_odds(
        self,
        regions: str = "us",
        markets: str = "h2h",
        bookmakers: Optional[str] = None,
    ) -> List[Dict]:
        """Return current NBA moneyline odds for all available games."""
        params: Dict = {
            "apiKey": self._api_key,
            "regions": regions,
            "markets": markets,
            "oddsFormat": "decimal",
        }
        if bookmakers:
            params["bookmakers"] = bookmakers

        url = f"{_BASE_URL}/sports/{_NBA_SPORT_KEY}/odds"
        with httpx.Client(timeout=10) as client:
            response = client.get(url, params=params)
            response.raise_for_status()

        data = response.json()
        logger.debug("Fetched odds for %d games", len(data))
        return data

    # ------------------------------------------------------------------
    # Player props
    # ------------------------------------------------------------------

    def get_prop_odds(
        self,
        event_id: str,
        prop_markets: str = "player_points,player_rebounds,player_assists",
    ) -> List[Dict]:
        """Return player-prop odds for a specific game event ID."""
        params: Dict = {
            "apiKey": self._api_key,
            "regions": "us",
            "markets": prop_markets,
            "oddsFormat": "decimal",
        }
        url = f"{_BASE_URL}/sports/{_NBA_SPORT_KEY}/events/{event_id}/odds"
        with httpx.Client(timeout=10) as client:
            response = client.get(url, params=params)
            response.raise_for_status()

        data = response.json()
        logger.debug("Fetched prop odds for event %s", event_id)
        return data

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def decimal_to_implied_prob(decimal_odds: float) -> float:
        """Convert decimal odds to implied probability (with no vig adjustment)."""
        if decimal_odds <= 0:
            return 0.0
        return 1.0 / decimal_odds
