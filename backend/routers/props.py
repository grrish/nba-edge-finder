"""Router for player prop predictions and edge-finding."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status

from models.schemas import EdgeListResponse, PropPrediction, PropPredictionRequest
from services.edge_engine import EdgeEngine
from services.nba_data import NBADataService
from services.odds import OddsService
from services.polymarket import PolymarketService

router = APIRouter(prefix="/props", tags=["props"])


def _get_edge_engine() -> EdgeEngine:
    return EdgeEngine(
        nba_service=NBADataService(),
        odds_service=OddsService(),
        polymarket_service=PolymarketService(),
    )


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
