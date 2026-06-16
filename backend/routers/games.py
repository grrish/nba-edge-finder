"""Router for game-level predictions and edge-finding."""

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from models.schemas import EdgeListResponse, GamePrediction, GamePredictionRequest
from services.edge_engine import EdgeEngine
from services.nba_data import NBADataService
from services.odds import OddsService
from services.polymarket import PolymarketService

router = APIRouter(prefix="/games", tags=["games"])


def _get_edge_engine() -> EdgeEngine:
    return EdgeEngine(
        nba_service=NBADataService(),
        odds_service=OddsService(),
        polymarket_service=PolymarketService(),
    )


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
