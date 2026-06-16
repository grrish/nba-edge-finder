"""ML prediction models for game outcomes and player props."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from models.schemas import GamePrediction, PlayerInfo, PropPrediction, TeamInfo

logger = logging.getLogger(__name__)

_MODEL_VERSION = "0.1.0-scaffold"


class NBAPredictor:
    """XGBoost-backed predictor for game outcomes and player props.

    Models are trained offline and loaded from disk. The scaffold ships
    with untrained placeholder logic; replace _game_model and _prop_model
    with fitted XGBClassifier / XGBRegressor instances.
    """

    def __init__(self) -> None:
        self._game_model = None   # XGBClassifier, loaded via _load_game_model()
        self._prop_model = None   # XGBRegressor,  loaded via _load_prop_model()

    # ------------------------------------------------------------------
    # Game outcome
    # ------------------------------------------------------------------

    def predict_game_outcome(
        self,
        home_team_id: str,
        away_team_id: str,
        home_log: pd.DataFrame,
        away_log: pd.DataFrame,
    ) -> GamePrediction:
        """Return win probabilities for a matchup.

        Feature engineering:
          - rolling average PTS, OPP_PTS, pace proxy for last 10 games
          - home/away split indicator
        """
        home_features = self._extract_team_features(home_log, is_home=True)
        away_features = self._extract_team_features(away_log, is_home=False)
        feature_vector = np.concatenate([home_features, away_features]).reshape(1, -1)

        if self._game_model is not None:
            home_win_prob = float(self._game_model.predict_proba(feature_vector)[0][1])
        else:
            # Naive home-court advantage prior until model is trained
            home_avg_pts = float(home_log["PTS"].mean()) if "PTS" in home_log.columns else 110.0
            away_avg_pts = float(away_log["PTS"].mean()) if "PTS" in away_log.columns else 108.0
            total = home_avg_pts + away_avg_pts
            home_win_prob = home_avg_pts / total if total > 0 else 0.52

        away_win_prob = 1.0 - home_win_prob

        return GamePrediction(
            game_id=f"{home_team_id}_vs_{away_team_id}_{datetime.utcnow().date()}",
            home_team=TeamInfo(id=home_team_id, name=home_team_id, abbreviation=""),
            away_team=TeamInfo(id=away_team_id, name=away_team_id, abbreviation=""),
            home_win_probability=round(home_win_prob, 4),
            away_win_probability=round(away_win_prob, 4),
            predicted_home_score=float(home_log["PTS"].mean()) if "PTS" in home_log.columns else 110.0,
            predicted_away_score=float(away_log["PTS"].mean()) if "PTS" in away_log.columns else 108.0,
            confidence=0.6 if self._game_model is None else 0.8,
            model_version=_MODEL_VERSION,
        )

    # ------------------------------------------------------------------
    # Player props
    # ------------------------------------------------------------------

    def predict_prop_outcome(
        self,
        player_id: str,
        prop_type: str,
        line: float,
        player_log: pd.DataFrame,
    ) -> PropPrediction:
        """Return over/under probabilities for a player prop line.

        Uses a rolling mean + standard deviation to estimate probability
        until a trained regression model is available.
        """
        stat_col = self._prop_type_to_column(prop_type)
        if stat_col in player_log.columns:
            values = player_log[stat_col].dropna().astype(float)
            mu = float(values.mean())
            sigma = float(values.std()) if len(values) > 1 else 5.0
        else:
            mu, sigma = line, 5.0

        if self._prop_model is not None:
            projected = float(self._prop_model.predict([[player_id, prop_type, line]])[0])
        else:
            projected = mu

        from scipy import stats as scipy_stats
        over_prob = float(1 - scipy_stats.norm.cdf(line, loc=mu, scale=max(sigma, 0.1)))
        under_prob = 1.0 - over_prob

        return PropPrediction(
            player=PlayerInfo(id=player_id, name=player_id, team_id=""),
            game_id="",
            prop_type=prop_type,
            projected_value=round(projected, 2),
            over_probability=round(over_prob, 4),
            under_probability=round(under_prob, 4),
            line=line,
            confidence=0.55 if self._prop_model is None else 0.75,
            model_version=_MODEL_VERSION,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_team_features(log: pd.DataFrame, is_home: bool) -> np.ndarray:
        """Build a 1-D feature vector from a team game log."""
        def safe_mean(col: str) -> float:
            return float(log[col].mean()) if col in log.columns else 0.0

        return np.array([
            safe_mean("PTS"),
            safe_mean("OPP_PTS") if "OPP_PTS" in log.columns else 0.0,
            safe_mean("FG_PCT") if "FG_PCT" in log.columns else 0.0,
            safe_mean("FG3_PCT") if "FG3_PCT" in log.columns else 0.0,
            float(is_home),
        ])

    @staticmethod
    def _prop_type_to_column(prop_type: str) -> str:
        mapping = {
            "points": "PTS",
            "rebounds": "REB",
            "assists": "AST",
            "three_pointers": "FG3M",
            "steals": "STL",
            "blocks": "BLK",
        }
        return mapping.get(prop_type.lower(), prop_type.upper())
