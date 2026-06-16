from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------


class TeamInfo(BaseModel):
    id: str
    name: str
    abbreviation: str


class PlayerInfo(BaseModel):
    id: str
    name: str
    team_id: str


# ---------------------------------------------------------------------------
# Game prediction
# ---------------------------------------------------------------------------


class GamePredictionRequest(BaseModel):
    home_team_id: str = Field(..., description="NBA team ID for the home side")
    away_team_id: str = Field(..., description="NBA team ID for the away side")
    game_date: datetime = Field(..., description="Scheduled tip-off time (UTC)")


class GamePrediction(BaseModel):
    game_id: str
    home_team: TeamInfo
    away_team: TeamInfo
    home_win_probability: float = Field(..., ge=0.0, le=1.0)
    away_win_probability: float = Field(..., ge=0.0, le=1.0)
    predicted_home_score: float
    predicted_away_score: float
    confidence: float = Field(..., ge=0.0, le=1.0)
    model_version: str


# ---------------------------------------------------------------------------
# Prop prediction
# ---------------------------------------------------------------------------


class PropPredictionRequest(BaseModel):
    player_id: str = Field(..., description="NBA player ID")
    game_id: str
    prop_type: str = Field(
        ...,
        description="e.g. 'points', 'rebounds', 'assists', 'three_pointers'",
    )
    line: float = Field(..., description="Sportsbook over/under line")


class PropPrediction(BaseModel):
    player: PlayerInfo
    game_id: str
    prop_type: str
    projected_value: float
    over_probability: float = Field(..., ge=0.0, le=1.0)
    under_probability: float = Field(..., ge=0.0, le=1.0)
    line: float
    confidence: float = Field(..., ge=0.0, le=1.0)
    model_version: str


# ---------------------------------------------------------------------------
# Edge / +EV scoring
# ---------------------------------------------------------------------------


class MarketPrice(BaseModel):
    source: str = Field(..., description="e.g. 'polymarket', 'draftkings', 'fanduel'")
    implied_probability: float = Field(..., ge=0.0, le=1.0)
    odds_american: Optional[int] = None
    odds_decimal: Optional[float] = None


class EdgeScore(BaseModel):
    event_id: str
    event_type: str = Field(..., description="'game' or 'prop'")
    description: str
    model_probability: float = Field(..., ge=0.0, le=1.0)
    market_prices: List[MarketPrice]
    best_edge: float = Field(..., description="Model prob minus best implied prob")
    best_source: str
    kelly_fraction: float = Field(..., ge=0.0, description="Kelly criterion stake")
    is_positive_ev: bool


class EdgeListResponse(BaseModel):
    edges: List[EdgeScore]
    generated_at: datetime
    total_opportunities: int


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    environment: str
