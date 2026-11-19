"""Persistent, append-only SQLite store for sportsbook odds snapshots.

Separate from services/cache.py's cache.db (TTL-based, ephemeral): this one
accumulates one row per (game, bookmaker, fetch) indefinitely — multiple
snapshots of the same game are kept, not deduped, since price movement over
time is the point.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, List

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


class OddsHistoryStore:
    """SQLite-backed append-only store for odds snapshots."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(path)
        self._init_schema()

    @staticmethod
    def resolve_path(odds_history_db_path: str) -> Path:
        """Resolve a Settings.odds_history_db_path value against backend/."""
        p = Path(odds_history_db_path)
        return p if p.is_absolute() else _BACKEND_ROOT / p

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS odds_snapshots (
                    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                    fetched_at             TEXT NOT NULL,
                    game_id                TEXT NOT NULL,
                    commence_time          TEXT,
                    home_team              TEXT NOT NULL,
                    away_team              TEXT NOT NULL,
                    bookmaker              TEXT NOT NULL,
                    bookmaker_last_update  TEXT,
                    home_american_odds     INTEGER,
                    away_american_odds     INTEGER
                )
                """
            )
            # Migration for DBs created before bookmaker_last_update existed —
            # add it in place rather than recreating the table, so existing
            # snapshot rows survive.
            existing_cols = {
                row["name"] for row in conn.execute("PRAGMA table_info(odds_snapshots)")
            }
            if "bookmaker_last_update" not in existing_cols:
                conn.execute("ALTER TABLE odds_snapshots ADD COLUMN bookmaker_last_update TEXT")

    def append_many(self, rows: List[Dict]) -> int:
        """Append *rows* as new snapshot rows. No dedupe — returns the count written."""
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO odds_snapshots
                    (fetched_at, game_id, commence_time, home_team, away_team,
                     bookmaker, bookmaker_last_update, home_american_odds, away_american_odds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r["fetched_at"],
                        r["game_id"],
                        r.get("commence_time"),
                        r["home_team"],
                        r["away_team"],
                        r["bookmaker"],
                        r.get("bookmaker_last_update"),
                        r.get("home_american_odds"),
                        r.get("away_american_odds"),
                    )
                    for r in rows
                ],
            )
        return len(rows)

    def total_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM odds_snapshots").fetchone()
        return row["n"]
