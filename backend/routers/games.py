"""Router for game-level predictions, odds, and edge-finding."""

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from models.schemas import (
    EdgeListResponse,
    GameOdds,
    GamePrediction,
    GamePredictionRequest,
    GameWithMarkets,
    PolymarketMarket,
    TodayGamesResponse,
    TodayMarketsResponse,
)
from services.edge_engine import EdgeEngine
from services.nba_data import NBADataService
from services.odds import OddsService
from services.polymarket import PolymarketService

router = APIRouter(prefix="/games", tags=["games"])


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------


def _get_odds_service() -> OddsService:
    return OddsService()


def _get_poly_service() -> PolymarketService:
    return PolymarketService()


def _get_nba_service() -> NBADataService:
    return NBADataService()


def _get_edge_engine() -> EdgeEngine:
    return EdgeEngine(
        nba_service=NBADataService(),
        odds_service=OddsService(),
        polymarket_service=PolymarketService(),
    )


# ---------------------------------------------------------------------------
# NEW — today's lines
# ---------------------------------------------------------------------------


@router.get(
    "/today",
    response_model=TodayGamesResponse,
    status_code=status.HTTP_200_OK,
    summary="Today's NBA game lines",
    description=(
        "Return all NBA games on today's slate with best available moneyline, "
        "spread, and total from The Odds API. During the offseason the games "
        "list will be empty."
    ),
)
async def today_games(
    odds: OddsService = Depends(_get_odds_service),
) -> TodayGamesResponse:
    """Live NBA game lines from The Odds API, 30-minute cache."""
    raw = odds.get_nba_game_lines(sport="basketball_nba")
    games = [GameOdds(**g) for g in raw]
    return TodayGamesResponse(
        games=games,
        count=len(games),
        generated_at=datetime.utcnow(),
        sport="basketball_nba",
    )


@router.get(
    "/today/markets",
    response_model=TodayMarketsResponse,
    status_code=status.HTTP_200_OK,
    summary="Today's games with Polymarket prices attached",
    description=(
        "Return today's NBA games paired with the best-matching Polymarket "
        "market for each game, if one exists. Prices from both sportsbooks "
        "and prediction markets in one response."
    ),
)
async def today_games_with_markets(
    odds: OddsService = Depends(_get_odds_service),
    poly: PolymarketService = Depends(_get_poly_service),
) -> TodayMarketsResponse:
    """NBA game lines + Polymarket prices, matched by team name."""
    raw_games   = odds.get_nba_game_lines(sport="basketball_nba")
    poly_mkts   = poly.get_nba_markets()

    results: List[GameWithMarkets] = []
    for g in raw_games:
        game_schema = GameOdds(**g)

        matched_raw = poly.match_to_game(
            # build a pseudo-market dict with the question for matching
            {"question": f"{g['home_team']} vs {g['away_team']}"},
            [g],
        )
        # Try all poly markets against this game
        poly_schema: PolymarketMarket | None = None
        for pm in poly_mkts:
            if poly.match_to_game(pm, [g]):
                try:
                    poly_schema = PolymarketMarket(**pm)
                except Exception:
                    pass
                break

        results.append(GameWithMarkets(game=game_schema, polymarket=poly_schema))

    return TodayMarketsResponse(
        games=results,
        count=len(results),
        generated_at=datetime.utcnow(),
    )


# ---------------------------------------------------------------------------
# EXISTING — ML predictions + edge scoring
# ---------------------------------------------------------------------------


@router.post(
    "/predict",
    response_model=GamePrediction,
    status_code=status.HTTP_200_OK,
    summary="Predict game outcome",
    description="Run the ML model against a scheduled matchup and return win probabilities.",
)
async def predict_game(
    payload: GamePredictionRequest,
    engine: EdgeEngine = Depends(_get_edge_engine),
) -> GamePrediction:
    """Return win-probability predictions for a single game."""
    prediction = await engine.predict_game(payload)
    if prediction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Could not generate prediction — check team IDs and date.",
        )
    return prediction


@router.get(
    "/edges",
    response_model=EdgeListResponse,
    status_code=status.HTTP_200_OK,
    summary="List +EV game opportunities",
    description="Return all game markets where the model finds positive expected value.",
)
async def list_game_edges(
    engine: EdgeEngine = Depends(_get_edge_engine),
) -> EdgeListResponse:
    """Scan today's games and surface +EV opportunities."""
    edges = await engine.find_game_edges()
    return EdgeListResponse(
        edges=edges,
        generated_at=datetime.utcnow(),
        total_opportunities=len(edges),
    )


@router.get(
    "/{game_id}/edge",
    response_model=EdgeListResponse,
    status_code=status.HTTP_200_OK,
    summary="Edge score for a specific game",
)
async def game_edge(
    game_id: str,
    engine: EdgeEngine = Depends(_get_edge_engine),
) -> EdgeListResponse:
    """Return edge scores for a specific game ID."""
    edges = await engine.find_game_edges(game_id=game_id)
    return EdgeListResponse(
        edges=edges,
        generated_at=datetime.utcnow(),
        total_opportunities=len(edges),
    )
