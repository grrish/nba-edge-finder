"""Polymarket prediction-market data service."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_GAMMA_BASE = "https://gamma-api.polymarket.com"
_CLOB_BASE = "https://clob.polymarket.com"


class PolymarketService:
    """Fetch NBA market prices from Polymarket's Gamma and CLOB APIs."""

    # ------------------------------------------------------------------
    # Market discovery
    # ------------------------------------------------------------------

    def search_nba_markets(self, query: str = "NBA", limit: int = 50) -> List[Dict]:
        """Return open NBA prediction markets from the Gamma API."""
        params = {
            "q": query,
            "closed": "false",
            "limit": limit,
        }
        url = f"{_GAMMA_BASE}/markets"
        with httpx.Client(timeout=10) as client:
            response = client.get(url, params=params)
            response.raise_for_status()

        markets = response.json()
        logger.debug("Found %d Polymarket NBA markets", len(markets))
        return markets

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------

    def get_market_price(self, condition_id: str) -> Optional[Dict]:
        """Return current best-bid / best-ask for a Polymarket condition ID."""
        url = f"{_CLOB_BASE}/book"
        params = {"token_id": condition_id}
        with httpx.Client(timeout=10) as client:
            response = client.get(url, params=params)
            if response.status_code == 404:
                logger.warning("Condition %s not found on CLOB", condition_id)
                return None
            response.raise_for_status()

        book = response.json()
        best_bid = float(book["bids"][0]["price"]) if book.get("bids") else 0.0
        best_ask = float(book["asks"][0]["price"]) if book.get("asks") else 1.0

        return {
            "condition_id": condition_id,
            "mid_price": (best_bid + best_ask) / 2,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "implied_probability": (best_bid + best_ask) / 2,
        }

    def get_markets_by_team(self, team_name: str) -> List[Dict]:
        """Return all open Polymarket markets that mention a specific team."""
        return self.search_nba_markets(query=team_name)
