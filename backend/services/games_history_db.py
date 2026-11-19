"""Persistent SQLite store for backfilled historical game results.

Separate from services/cache.py's cache.db: that store is a TTL-based cache
for fetched market/API data; this one holds team-level game results
indefinitely, as groundwork for training a real predictor later — rows live
until the backfill script re-writes them.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


class GamesHistoryStore:
    """SQLite-backed upsert store for backfilled team-level game results."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(path)
        self._init_schema()

    @staticmethod
    def resolve_path(games_history_db_path: str) -> Path:
        """Resolve a Settings.games_history_db_path value against backend/."""
        p = Path(games_history_db_path)
        return p if p.is_absolute() else _BACKEND_ROOT / p

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS games (
                    game_id    TEXT PRIMARY KEY,
                    season     TEXT NOT NULL,
                    league_id  TEXT NOT NULL,
                    game_date  TEXT NOT NULL,
                    home_team  TEXT NOT NULL,
                    away_team  TEXT NOT NULL,
                    home_score INTEGER,
                    away_score INTEGER,
                    winner     TEXT NOT NULL,
                    game_type  TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            # Migration for DBs created before game_type existed — add it in
            # place rather than recreating the table, so existing rows survive.
            existing_cols = {
                row["name"] for row in conn.execute("PRAGMA table_info(games)")
            }
            if "game_type" not in existing_cols:
                conn.execute("ALTER TABLE games ADD COLUMN game_type TEXT")

    def upsert_many(self, rows: List[Dict]) -> int:
        """Insert or update *rows* by game_id. Returns the number of rows written."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO games
                    (game_id, season, league_id, game_date, home_team, away_team,
                     home_score, away_score, winner, game_type, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    season=excluded.season,
                    league_id=excluded.league_id,
                    game_date=excluded.game_date,
                    home_team=excluded.home_team,
                    away_team=excluded.away_team,
                    home_score=excluded.home_score,
                    away_score=excluded.away_score,
                    winner=excluded.winner,
                    game_type=excluded.game_type,
                    updated_at=excluded.updated_at
                """,
                [
                    (
                        r["game_id"],
                        r["season"],
                        r["league_id"],
                        r["game_date"],
                        r["home_team"],
                        r["away_team"],
                        r.get("home_score"),
                        r.get("away_score"),
                        r["winner"],
                        r.get("game_type"),
                        now,
                    )
                    for r in rows
                ],
            )
        return len(rows)

    def count_by_season(self, league_id: Optional[str] = None) -> Dict[str, int]:
        query = "SELECT season, COUNT(*) AS n FROM games"
        params: tuple = ()
        if league_id is not None:
            query += " WHERE league_id = ?"
            params = (league_id,)
        query += " GROUP BY season ORDER BY season"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return {r["season"]: r["n"] for r in rows}

    def total_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM games").fetchone()
        return row["n"]
