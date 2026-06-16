"""Core edge-finding engine: combine ML predictions with market prices."""

from __future__ import annotations

import logging
from typing import List, Optional

from models.schemas import (
    EdgeScore,
    GamePrediction,
    GamePredictionRequest,
    MarketPrice,
    PropPrediction,
    PropPredictionRequest,
)
from models.predictor import NBAPredictor
from services.nba_data import NBADataService
from services.odds import OddsService
from services.polymarket import PolymarketService

logger = logging.getLogger(__name__)

_MIN_EDGE_THRESHOLD = 0.02  # only surface opportunities with ≥2 % edge


class EdgeEngine:
    """Orchestrate predictions and market data to identify +EV bets."""

    def __init__(
        self,
        nba_service: NBADataService,
        odds_service: OddsService,
        polymarket_service: PolymarketService,
    ) -> None:
        self._nba = nba_service
        self._odds = odds_service
        self._poly = polymarket_service
        self._predictor = NBAPredictor()

    # ------------------------------------------------------------------
    # Game-level
    # ------------------------------------------------------------------

    async def predict_game(
        self, request: GamePredictionRequest
    ) -> Optional[GamePrediction]:
        """Return ML win-probability predictions for a scheduled game."""
        try:
            home_log = self._nba.get_team_game_log(request.home_team_id)
            away_log = self._nba.get_team_game_log(request.away_team_id)
            prediction = self._predictor.predict_game_outcome(
                home_team_id=request.home_team_id,
                away_team_id=request.away_team_id,
                home_log=home_log,
                away_log=away_log,
            )
            return prediction
        except Exception:
            logger.exception("Error predicting game %s vs %s", request.home_team_id, request.away_team_id)
            return None

    async def find_game_edges(self, game_id: Optional[str] = None) -> List[EdgeScore]:
        """Return +EV game-winner opportunities for today's slate."""
        edges: List[EdgeScore] = []
        try:
            market_odds = self._odds.get_game_odds()
        except Exception:
            logger.exception("Failed to fetch game odds")
            return edges

        for game in market_odds:
            if game_id and game.get("id") != game_id:
                continue
            edge = self._score_game_edge(game)
            if edge and edge.is_positive_ev:
                edges.append(edge)

        edges.sort(key=lambda e: e.best_edge, reverse=True)
        return edges

    def _score_game_edge(self, game: dict) -> Optional[EdgeScore]:
        """Build an EdgeScore for a single game dict from the Odds API."""
        try:
            home_team = game["home_team"]
            away_team = game["away_team"]
            event_id = game["id"]

            market_prices: List[MarketPrice] = []
            best_implied: float = 1.0
            best_source: str = ""

            for bookmaker in game.get("bookmakers", []):
                for market in bookmaker.get("markets", []):
                    if market["key"] != "h2h":
                        continue
                    for outcome in market.get("outcomes", []):
                        if outcome["name"] != home_team:
                            continue
                        decimal = float(outcome["price"])
                        implied = self._odds.decimal_to_implied_prob(decimal)
                        mp = MarketPrice(
                            source=bookmaker["key"],
                            implied_probability=implied,
                            odds_decimal=decimal,
                        )
                        market_prices.append(mp)
                        if implied < best_implied:
                            best_implied = implied
                            best_source = bookmaker["key"]

            # TODO: integrate ML model probability once predictor is trained
            # Placeholder: use 0.5 until the model is wired in
            model_prob: float = 0.5
            edge_value = model_prob - best_implied

            return EdgeScore(
                event_id=event_id,
                event_type="game",
                description=f"{away_team} @ {home_team} — home win",
                model_probability=model_prob,
                market_prices=market_prices,
                best_edge=edge_value,
                best_source=best_source,
                kelly_fraction=max(0.0, edge_value / (1 - best_implied)) if best_implied < 1 else 0.0,
                is_positive_ev=edge_value >= _MIN_EDGE_THRESHOLD,
            )
        except Exception:
            logger.exception("Error scoring game edge for event %s", game.get("id"))
            return None

    # ------------------------------------------------------------------
    # Prop-level
    # ------------------------------------------------------------------

    async def predict_prop(
        self, request: PropPredictionRequest
    ) -> Optional[PropPrediction]:
        """Return ML over/under probabilities for a player prop."""
        try:
            player_log = self._nba.get_player_game_log(request.player_id)
            prediction = self._predictor.predict_prop_outcome(
                player_id=request.player_id,
                prop_type=request.prop_type,
                line=request.line,
                player_log=player_log,
            )
            return prediction
        except Exception:
            logger.exception("Error predicting prop for player %s", request.player_id)
            return None

    async def find_prop_edges(
        self, player_id: Optional[str] = None
    ) -> List[EdgeScore]:
        """Return +EV prop opportunities for today's slate."""
        # Full implementation will iterate today's games, fetch prop odds,
        # run the ML model, and score each prop line.
        logger.info("Prop edge scanning — player_id filter: %s", player_id)
        return []
