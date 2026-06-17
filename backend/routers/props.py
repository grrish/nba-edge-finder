"""Router for player prop predictions, odds, and edge-finding."""

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from models.schemas import (
    EdgeListResponse,
    PropOdds,
    PropPrediction,
    PropPredictionRequest,
    TodayPropsResponse,
)
from services.edge_engine import EdgeEngine
from services.nba_data import NBADataService
from services.odds import OddsService
from services.polymarket import PolymarketService

router = APIRouter(prefix="/props", tags=["props"])


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------


def _get_odds_service() -> OddsService:
    return OddsService()


def _get_edge_engine() -> EdgeEngine:
    return EdgeEngine(
        nba_service=NBADataService(),
        odds_service=OddsService(),
        polymarket_service=PolymarketService(),
    )


# ---------------------------------------------------------------------------
# NEW — today's prop lines
# ---------------------------------------------------------------------------


@router.get(
    "/today",
    response_model=TodayPropsResponse,
    status_code=status.HTTP_200_OK,
    summary="All player props for today's NBA games",
    description=(
        "Fetch player prop lines (points / rebounds / assists) for every NBA "
        "game on today's slate. Uses The Odds API with a 30-minute cache. "
        "Returns an empty list during the offseason."
    ),
)
async def today_props(
    odds: OddsService = Depends(_get_odds_service),
) -> TodayPropsResponse:
    """Live NBA player props from The Odds API."""
    games = odds.get_nba_game_lines(sport="basketball_nba")

    all_props: List[PropOdds] = []
    for game in games:
        raw_props = odds.get_nba_player_props(game["game_id"], sport="basketball_nba")
        for p in raw_props:
            try:
                all_props.append(PropOdds(**p))
            except Exception:
                pass  # skip malformed rows

    return TodayPropsResponse(
        props=all_props,
        count=len(all_props),
        generated_at=datetime.utcnow(),
    )


# ---------------------------------------------------------------------------
# EXISTING — ML predictions + edge scoring
# ---------------------------------------------------------------------------


@router.post(
    "/predict",
    response_model=PropPrediction,
    status_code=status.HTTP_200_OK,
    summary="Predict player prop outcome",
    description="Return over/under probabilities for a player prop line.",
)
async def predict_prop(
    payload: PropPredictionRequest,
    engine: EdgeEngine = Depends(_get_edge_engine),
) -> PropPrediction:
    """Run the ML model for a single player prop."""
    prediction = await engine.predict_prop(payload)
    if prediction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Could not generate prop prediction — check player ID and prop type.",
        )
    return prediction


@router.get(
    "/edges",
    response_model=EdgeListResponse,
    status_code=status.HTTP_200_OK,
    summary="List +EV prop opportunities",
    description="Return all player prop markets where the model finds positive expected value.",
)
async def list_prop_edges(
    engine: EdgeEngine = Depends(_get_edge_engine),
) -> EdgeListResponse:
    """Scan today's props and surface +EV opportunities."""
    edges = await engine.find_prop_edges()
    return EdgeListResponse(
        edges=edges,
        generated_at=datetime.utcnow(),
        total_opportunities=len(edges),
    )


@router.get(
    "/{player_id}/edges",
    response_model=EdgeListResponse,
    status_code=status.HTTP_200_OK,
    summary="All prop edges for a player",
)
async def player_prop_edges(
    player_id: str,
    engine: EdgeEngine = Depends(_get_edge_engine),
) -> EdgeListResponse:
    """Return all prop edge opportunities for a specific player."""
    edges = await engine.find_prop_edges(player_id=player_id)
    return EdgeListResponse(
        edges=edges,
        generated_at=datetime.utcnow(),
        total_opportunities=len(edges),
    )
