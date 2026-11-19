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

--col-winner accepts either a home-win flag (1/0, True/false) or the
winning team's id (matched against --col-home-team/--col-away-team).

If the CSV has no season column, pass --derive-season to compute the
season label from --col-date instead (Sep 15 onward belongs to the new
season starting that year; before Sep 15 belongs to the previous one;
the 2020 bubble finals, Sep 30 - Oct 12, are pinned to season 2019-20).

--since-date YYYY-MM-DD skips rows dated before it.

--col-game-type populates an optional game_type column (e.g. Regular/
Playoffs/Preseason) when the CSV has one; silently omitted otherwise.

game_date is always stored as YYYY-MM-DD (any time-of-day component in
the source column is dropped).

Upsert on game_id: re-running the same (or an overlapping) CSV never
duplicates rows — matching game_ids are overwritten in place.

Usage (from backend/):
    python scripts/backfill_games.py --csv path/to/games.csv
    python scripts/backfill_games.py --csv path/to/wnba_games.csv --league-id 10
    python scripts/backfill_games.py --csv path/to/games_2026.csv \
        --col-game-id gameId --col-date gameDateTimeEst \
        --col-home-team hometeamId --col-away-team awayteamId \
        --col-home-score homeScore --col-away-score awayScore \
        --col-winner winner --derive-season --since-date 2022-10-01
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_settings  # noqa: E402
from services.games_history_db import GamesHistoryStore  # noqa: E402

logger = logging.getLogger(__name__)

NBA_LEAGUE_ID = "00"
WNBA_LEAGUE_ID = "10"

_BUBBLE_FINALS_START = date(2020, 9, 30)
_BUBBLE_FINALS_END = date(2020, 10, 12)


def normalize_season(raw: str) -> str:
    """"2022" -> "2022-23"; already-hyphenated labels pass through unchanged."""
    raw = raw.strip()
    if raw.isdigit():
        year = int(raw)
        return f"{year}-{str(year + 1)[-2:]}"
    return raw


def derive_season(d: date) -> str:
    """Season label from a game date: Sep 15 onward (through December)
    belongs to the new season starting that year; before Sep 15 belongs to
    the previous year's season. The 2020 bubble finals ran Sep 30 - Oct 12,
    so that window is pinned to season 2019-20 (it would otherwise fall in
    2020-21 under the plain day-of-year rule)."""
    if _BUBBLE_FINALS_START <= d <= _BUBBLE_FINALS_END:
        return "2019-20"
    new_season_started = d.month >= 10 or (d.month == 9 and d.day >= 15)
    year = d.year if new_season_started else d.year - 1
    return f"{year}-{str(year + 1)[-2:]}"


def parse_date_only(raw: str) -> date:
    """Drop any time-of-day component and parse the remaining YYYY-MM-DD."""
    date_part = raw.strip().split("T")[0].split(" ")[0]
    return date.fromisoformat(date_part)


def resolve_winner(
    raw: Dict[str, str],
    col_winner: Optional[str],
    col_home_team: str,
    col_away_team: str,
    home_score: Optional[int],
    away_score: Optional[int],
) -> Optional[str]:
    """Return "home"/"away", or None if it can't be determined.

    *col_winner* may hold a home-win flag (1/0, True/false) or the winning
    team's id — tried against --col-home-team/--col-away-team's raw values.
    Falls back to comparing scores when no winner column is usable.
    """
    if col_winner:
        val = str(raw.get(col_winner, "")).strip()
        if val:
            if val in ("1", "True", "true"):
                return "home"
            if val in ("0", "False", "false"):
                return "away"
            home_id = str(raw.get(col_home_team, "")).strip()
            away_id = str(raw.get(col_away_team, "")).strip()
            if val == home_id:
                return "home"
            if val == away_id:
                return "away"

    if home_score is not None and away_score is not None:
        return "home" if home_score >= away_score else "away"
    return None


def read_csv_rows(
    csv_path: Path,
    league_id: str,
    col_game_id: str,
    col_date: str,
    col_season: Optional[str],
    derive_season_flag: bool,
    col_home_team: str,
    col_away_team: str,
    col_home_score: str,
    col_away_score: str,
    col_winner: Optional[str],
    since_date: Optional[date],
    col_game_type: Optional[str],
) -> List[Dict]:
    rows: List[Dict] = []
    skipped = 0
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        has_game_type = bool(col_game_type) and col_game_type in fieldnames

        required = {col_game_id, col_date, col_home_team, col_away_team}
        if not derive_season_flag:
            required.add(col_season)
        missing = required - fieldnames
        if missing:
            raise ValueError(
                f"CSV is missing expected column(s) {sorted(missing)}. "
                f"Available columns: {reader.fieldnames}. "
                "Pass the matching --col-* flags to map your file's headers, "
                "or --derive-season if there's no season column."
            )

        for raw in reader:
            try:
                game_id = str(raw[col_game_id]).strip()
                if not game_id:
                    skipped += 1
                    continue

                game_date = parse_date_only(raw[col_date])
                if since_date is not None and game_date < since_date:
                    continue

                home_score_raw = raw.get(col_home_score, "")
                away_score_raw = raw.get(col_away_score, "")
                home_score = int(float(home_score_raw)) if home_score_raw not in ("", None) else None
                away_score = int(float(away_score_raw)) if away_score_raw not in ("", None) else None

                winner = resolve_winner(
                    raw, col_winner, col_home_team, col_away_team, home_score, away_score
                )
                if winner is None:
                    skipped += 1
                    continue

                season = (
                    derive_season(game_date)
                    if derive_season_flag
                    else normalize_season(str(raw[col_season]))
                )

                rows.append(
                    {
                        "game_id": game_id,
                        "season": season,
                        "league_id": league_id,
                        "game_date": game_date.isoformat(),
                        "home_team": str(raw[col_home_team]).strip(),
                        "away_team": str(raw[col_away_team]).strip(),
                        "home_score": home_score,
                        "away_score": away_score,
                        "winner": winner,
                        "game_type": str(raw[col_game_type]).strip() if has_game_type else None,
                    }
                )
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping malformed row: %s (%s)", raw, exc)
                skipped += 1

    if skipped:
        logger.info("Skipped %d row(s) missing game_id/date/winner data", skipped)
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
    parser.add_argument(
        "--derive-season",
        action="store_true",
        help="Compute the season label from --col-date instead of reading --col-season "
        "(use when the CSV has no season column).",
    )
    parser.add_argument("--col-home-team", default="HOME_TEAM_ID")
    parser.add_argument("--col-away-team", default="VISITOR_TEAM_ID")
    parser.add_argument("--col-home-score", default="PTS_home")
    parser.add_argument("--col-away-score", default="PTS_away")
    parser.add_argument(
        "--col-winner",
        default="HOME_TEAM_WINS",
        help="Column holding either a home-win flag (1/0, True/false) or the winning "
        "team's id (matched against --col-home-team/--col-away-team). "
        "Pass an empty string to force deriving the winner from scores instead.",
    )
    parser.add_argument(
        "--since-date",
        default=None,
        help="YYYY-MM-DD — skip rows dated before this.",
    )
    parser.add_argument(
        "--col-game-type",
        default="GAME_TYPE",
        help="Column holding the game type (e.g. Regular/Playoffs/Preseason), if present. "
        "Silently omitted if the column isn't in the CSV.",
    )
    args = parser.parse_args()

    if not args.csv.exists():
        parser.error(f"CSV not found: {args.csv}")

    since_date = date.fromisoformat(args.since_date) if args.since_date else None

    settings = get_settings()
    store = GamesHistoryStore(GamesHistoryStore.resolve_path(settings.games_history_db_path))

    rows = read_csv_rows(
        args.csv,
        league_id=args.league_id,
        col_game_id=args.col_game_id,
        col_date=args.col_date,
        col_season=args.col_season,
        derive_season_flag=args.derive_season,
        col_home_team=args.col_home_team,
        col_away_team=args.col_away_team,
        col_home_score=args.col_home_score,
        col_away_score=args.col_away_score,
        col_winner=args.col_winner or None,
        since_date=since_date,
        col_game_type=args.col_game_type or None,
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
