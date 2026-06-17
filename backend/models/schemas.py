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
# Odds API response shapes
# ---------------------------------------------------------------------------


class BestOdds(BaseModel):
    bookmaker: str
    american_odds: int
    implied_prob: float = Field(..., ge=0.0, le=1.0)


class GameOdds(BaseModel):
    game_id: str
    sport: str
    home_team: str
    away_team: str
    commence_time: str
    home_best: Optional[BestOdds] = None
    away_best: Optional[BestOdds] = None
    home_prob_vig_free: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    away_prob_vig_free: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    spread_home: Optional[float] = None
    spread_bookmaker: Optional[str] = None
    total_line: Optional[float] = None
    total_bookmaker: Optional[str] = None


class PropOdds(BaseModel):
    game_id: str
    player_name: str
    stat_type: str
    line: float
    over_american: int
    under_american: int
    over_prob: float = Field(..., ge=0.0, le=1.0)
    under_prob: float = Field(..., ge=0.0, le=1.0)
    bookmaker: str


class TodayGamesResponse(BaseModel):
    games: List[GameOdds]
    count: int
    generated_at: datetime
    sport: str


class TodayPropsResponse(BaseModel):
    props: List[PropOdds]
    count: int
    generated_at: datetime


# ---------------------------------------------------------------------------
# Polymarket shapes
# ---------------------------------------------------------------------------


class PolymarketMarket(BaseModel):
    market_id: str
    question: str
    outcome_a: str
    outcome_b: str
    price_a: float = Field(..., ge=0.0, le=1.0)
    price_b: float = Field(..., ge=0.0, le=1.0)
    best_bid: float
    best_ask: float
    last_trade_price: float
    volume: float
    liquidity: float
    close_time: str
    active: bool
    closed: bool


class NBAMarketsResponse(BaseModel):
    markets: List[PolymarketMarket]
    count: int
    generated_at: datetime


class GameWithMarkets(BaseModel):
    game: GameOdds
    polymarket: Optional[PolymarketMarket] = None


class TodayMarketsResponse(BaseModel):
    games: List[GameWithMarkets]
    count: int
    generated_at: datetime


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    environment: str
