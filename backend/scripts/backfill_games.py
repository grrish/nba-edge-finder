#!/usr/bin/env python3
"""Backfill backend/data/games_history.db with team-level NBA game results.

Pulls the last 3 completed NBA seasons plus the current one and upserts them
into the persistent games_history.db (see services/games_history_db.py).
Re-runnable: re-running never creates duplicate rows (upsert on game_id).

Usage (from backend/):
    python scripts/backfill_games.py
    python scripts/backfill_games.py --seasons 2024-25 2025-26
    python scripts/backfill_games.py --include-wnba
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_settings  # noqa: E402
from services.games_history_db import GamesHistoryStore  # noqa: E402
from services.nba_data import NBADataService  # noqa: E402

logger = logging.getLogger(__name__)

NBA_LEAGUE_ID = "00"
WNBA_LEAGUE_ID = "10"


def current_nba_season(today: date) -> str:
    """NBA seasons start in October; "2026-27" style label."""
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def last_n_seasons(today: date, n: int) -> List[str]:
    """The current season plus the *n* completed ones before it, oldest first."""
    current = current_nba_season(today)
    start_year = int(current.split("-")[0])
    years = range(start_year - n, start_year + 1)
    return [f"{y}-{str(y + 1)[-2:]}" for y in years]


def backfill(seasons: List[str], include_wnba: bool) -> None:
    settings = get_settings()
    store = GamesHistoryStore(GamesHistoryStore.resolve_path(settings.games_history_db_path))
    nba = NBADataService()

    leagues = [NBA_LEAGUE_ID] + ([WNBA_LEAGUE_ID] if include_wnba else [])

    for league_id in leagues:
        for season in seasons:
            rows = nba.get_season_game_results(season, league_id=league_id)
            written = store.upsert_many(rows)
            logger.info(
                "league_id=%s season=%s: fetched=%d upserted=%d",
                league_id, season, len(rows), written,
            )

    print()
    print("Row counts by season (NBA):")
    for season, n in store.count_by_season(league_id=NBA_LEAGUE_ID).items():
        print(f"  {season}: {n}")
    if include_wnba:
        print("Row counts by season (WNBA):")
        for season, n in store.count_by_season(league_id=WNBA_LEAGUE_ID).items():
            print(f"  {season}: {n}")
    print(f"Total rows in store: {store.total_count()}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s  %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seasons",
        nargs="+",
        default=None,
        help="Explicit season labels (e.g. 2024-25 2025-26). "
        "Defaults to the current season plus the 3 before it.",
    )
    parser.add_argument(
        "--include-wnba",
        action="store_true",
        help="Also backfill the same seasons for the WNBA (league_id=10).",
    )
    args = parser.parse_args()

    seasons = args.seasons or last_n_seasons(date.today(), n=3)
    backfill(seasons, include_wnba=args.include_wnba)


if __name__ == "__main__":
    main()
