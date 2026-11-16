#!/usr/bin/env python3
"""Backfill backend/data/games_history.db from a downloaded CSV of game results.

stats.nba.com / the nba_api CDN are unreachable from this environment's
network (confirmed blocked even outside Python), so this imports from a CSV
you've already downloaded (e.g. a Kaggle NBA-games dataset) instead of
pulling live via NBADataService.get_season_game_results() — that method is
left in place in nba_data.py for whenever a live pull becomes possible again.

Column names vary by dataset, so every column is mappable via --col-* flags.
Defaults match the common Kaggle "games.csv" schema:
    GAME_DATE_EST, GAME_ID, HOME_TEAM_ID, VISITOR_TEAM_ID, SEASON,
    PTS_home, PTS_away, HOME_TEAM_WINS

Upsert on game_id: re-running the same (or an overlapping) CSV never
duplicates rows — matching game_ids are overwritten in place.

Usage (from backend/):
    python scripts/backfill_games.py --csv path/to/games.csv
    python scripts/backfill_games.py --csv path/to/wnba_games.csv --league-id 10
    python scripts/backfill_games.py --csv path/to/other.csv \
        --col-game-id GameId --col-date Date --col-season Season \
        --col-home-team HomeTeam --col-away-team AwayTeam \
        --col-home-score HomeScore --col-away-score AwayScore
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_settings  # noqa: E402
from services.games_history_db import GamesHistoryStore  # noqa: E402

logger = logging.getLogger(__name__)

NBA_LEAGUE_ID = "00"
WNBA_LEAGUE_ID = "10"


def normalize_season(raw: str) -> str:
    """"2022" -> "2022-23"; already-hyphenated labels pass through unchanged."""
    raw = raw.strip()
    if raw.isdigit():
        year = int(raw)
        return f"{year}-{str(year + 1)[-2:]}"
    return raw


def read_csv_rows(
    csv_path: Path,
    league_id: str,
    col_game_id: str,
    col_date: str,
    col_season: str,
    col_home_team: str,
    col_away_team: str,
    col_home_score: str,
    col_away_score: str,
    col_home_wins: Optional[str],
) -> List[Dict]:
    rows: List[Dict] = []
    skipped = 0
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = {col_game_id, col_date, col_season, col_home_team, col_away_team} - set(
            reader.fieldnames or []
        )
        if missing:
            raise ValueError(
                f"CSV is missing expected column(s) {sorted(missing)}. "
                f"Available columns: {reader.fieldnames}. "
                "Pass the matching --col-* flags to map your file's headers."
            )

        for raw in reader:
            try:
                game_id = str(raw[col_game_id]).strip()
                home_score_raw = raw.get(col_home_score, "")
                away_score_raw = raw.get(col_away_score, "")
                home_score = int(float(home_score_raw)) if home_score_raw not in ("", None) else None
                away_score = int(float(away_score_raw)) if away_score_raw not in ("", None) else None

                if col_home_wins and raw.get(col_home_wins, "") not in ("", None):
                    winner = "home" if str(raw[col_home_wins]).strip() in ("1", "True", "true") else "away"
                elif home_score is not None and away_score is not None:
                    winner = "home" if home_score >= away_score else "away"
                else:
                    skipped += 1
                    continue

                if not game_id:
                    skipped += 1
                    continue

                rows.append(
                    {
                        "game_id": game_id,
                        "season": normalize_season(str(raw[col_season])),
                        "league_id": league_id,
                        "game_date": str(raw[col_date]).strip(),
                        "home_team": str(raw[col_home_team]).strip(),
                        "away_team": str(raw[col_away_team]).strip(),
                        "home_score": home_score,
                        "away_score": away_score,
                        "winner": winner,
                    }
                )
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping malformed row: %s (%s)", raw, exc)
                skipped += 1

    if skipped:
        logger.info("Skipped %d row(s) missing game_id/winner/score data", skipped)
    return rows


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s  %(message)s")

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--csv", required=True, type=Path, help="Path to the downloaded CSV.")
    parser.add_argument(
        "--league-id",
        default=NBA_LEAGUE_ID,
        help=f"League id to tag every imported row with ({NBA_LEAGUE_ID}=NBA, {WNBA_LEAGUE_ID}=WNBA). Default: {NBA_LEAGUE_ID}.",
    )
    parser.add_argument("--col-game-id", default="GAME_ID")
    parser.add_argument("--col-date", default="GAME_DATE_EST")
    parser.add_argument("--col-season", default="SEASON")
    parser.add_argument("--col-home-team", default="HOME_TEAM_ID")
    parser.add_argument("--col-away-team", default="VISITOR_TEAM_ID")
    parser.add_argument("--col-home-score", default="PTS_home")
    parser.add_argument("--col-away-score", default="PTS_away")
    parser.add_argument(
        "--col-home-wins",
        default="HOME_TEAM_WINS",
        help="Column holding a home-win flag (1/0 or True/False). "
        "Pass an empty string to force deriving the winner from scores instead.",
    )
    args = parser.parse_args()

    if not args.csv.exists():
        parser.error(f"CSV not found: {args.csv}")

    settings = get_settings()
    store = GamesHistoryStore(GamesHistoryStore.resolve_path(settings.games_history_db_path))

    rows = read_csv_rows(
        args.csv,
        league_id=args.league_id,
        col_game_id=args.col_game_id,
        col_date=args.col_date,
        col_season=args.col_season,
        col_home_team=args.col_home_team,
        col_away_team=args.col_away_team,
        col_home_score=args.col_home_score,
        col_away_score=args.col_away_score,
        col_home_wins=args.col_home_wins or None,
    )
    written = store.upsert_many(rows)
    logger.info("Imported %d row(s) from %s (league_id=%s)", written, args.csv, args.league_id)

    print()
    print(f"Row counts by season (league_id={args.league_id}):")
    for season, n in store.count_by_season(league_id=args.league_id).items():
        print(f"  {season}: {n}")
    print(f"Total rows in store (all leagues): {store.total_count()}")


if __name__ == "__main__":
    main()
