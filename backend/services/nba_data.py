"""NBA data ingestion service using nba_api."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class NBADataService:
    """Fetch and cache NBA game logs, player stats, and schedule data."""

    def get_team_game_log(
        self,
        team_id: str,
        season: str = "2024-25",
        last_n: int = 20,
    ) -> pd.DataFrame:
        """Return the last *last_n* games for a team as a DataFrame.

        Columns: GAME_ID, GAME_DATE, MATCHUP, WL, PTS, OPP_PTS, ...
        """
        from nba_api.stats.endpoints import teamgamelog

        log = teamgamelog.TeamGameLog(
            team_id=team_id,
            season=season,
            season_type_all_star="Regular Season",
        )
        df = log.get_data_frames()[0].head(last_n)
        logger.debug("Fetched %d games for team %s", len(df), team_id)
        return df

    def get_player_game_log(
        self,
        player_id: str,
        season: str = "2024-25",
        last_n: int = 20,
    ) -> pd.DataFrame:
        """Return the last *last_n* games for a player as a DataFrame."""
        from nba_api.stats.endpoints import playergamelog

        log = playergamelog.PlayerGameLog(
            player_id=player_id,
            season=season,
            season_type_all_star="Regular Season",
        )
        df = log.get_data_frames()[0].head(last_n)
        logger.debug("Fetched %d games for player %s", len(df), player_id)
        return df

    def get_today_schedule(self) -> List[Dict]:
        """Return today's scheduled games as a list of dicts."""
        from nba_api.live.nba.endpoints import scoreboard

        board = scoreboard.ScoreBoard()
        games = board.games.get_dict()
        logger.debug("Today's schedule: %d games", len(games))
        return games

    def get_team_advanced_stats(
        self,
        team_id: str,
        season: str = "2024-25",
    ) -> Optional[Dict]:
        """Return season-level advanced stats for a team (OffRtg, DefRtg, Pace, ...)."""
        from nba_api.stats.endpoints import teamdashboardbygeneralsplits

        dash = teamdashboardbygeneralsplits.TeamDashboardByGeneralSplits(
            team_id=team_id,
            season=season,
        )
        df = dash.get_data_frames()[0]
        if df.empty:
            return None
        return df.iloc[0].to_dict()
