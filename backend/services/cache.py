"""Shared SQLite key-value cache with per-entry TTL.

Extracted so every service can share the same cache.db without
duplicating the connection/schema logic.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_DB_PATH = _DATA_DIR / "cache.db"


class CacheDB:
    """SQLite-backed key-value store with TTL expiry."""

    def __init__(self, path: Path = CACHE_DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key       TEXT PRIMARY KEY,
                    data      TEXT NOT NULL,
                    stored_at REAL NOT NULL,
                    ttl       INTEGER NOT NULL
                )
                """
            )

    def get(self, key: str) -> Optional[Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data, stored_at, ttl FROM cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            logger.debug("Cache MISS  key=%s", key)
            return None
        age = time.time() - row["stored_at"]
        if age > row["ttl"]:
            logger.debug("Cache EXPIRED  key=%s  age=%.0fs", key, age)
            return None
        logger.debug("Cache HIT   key=%s  age=%.0fs", key, age)
        return json.loads(row["data"])

    def set(self, key: str, data: Any, ttl: int) -> None:
        payload = json.dumps(data, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cache (key, data, stored_at, ttl)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    data=excluded.data,
                    stored_at=excluded.stored_at,
                    ttl=excluded.ttl
                """,
                (key, payload, time.time(), ttl),
            )
        logger.debug("Cache SET   key=%s  ttl=%ds", key, ttl)

    def delete(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
