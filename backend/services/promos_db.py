"""Persistent SQLite store for manually-logged sportsbook promos.

Separate from services/cache.py's cache.db: that store is a TTL-based cache
for fetched market data; this one is plain CRUD with no expiry semantics —
a promo row lives until the user deletes it.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from models.schemas import Promo, PromoCreate, PromoStatus

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


class PromoStore:
    """SQLite-backed CRUD store for promos."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(path)
        self._init_schema()

    @staticmethod
    def resolve_path(promos_db_path: str) -> Path:
        """Resolve a Settings.promos_db_path value against backend/."""
        p = Path(promos_db_path)
        return p if p.is_absolute() else _BACKEND_ROOT / p

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS promos (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    sportsbook  TEXT NOT NULL,
                    promo_type  TEXT NOT NULL,
                    amount      TEXT NOT NULL,
                    expiry_date TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    notes       TEXT,
                    created_at  TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _row_to_promo(row: sqlite3.Row) -> Promo:
        return Promo(
            id=row["id"],
            sportsbook=row["sportsbook"],
            promo_type=row["promo_type"],
            amount=row["amount"],
            expiry_date=row["expiry_date"],
            status=row["status"],
            notes=row["notes"],
            created_at=row["created_at"],
        )

    def create(self, payload: PromoCreate) -> Promo:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO promos
                    (sportsbook, promo_type, amount, expiry_date, status, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.sportsbook,
                    payload.promo_type.value,
                    payload.amount,
                    payload.expiry_date.isoformat(),
                    PromoStatus.available.value,
                    payload.notes,
                    created_at,
                ),
            )
            promo_id = cur.lastrowid
            row = conn.execute("SELECT * FROM promos WHERE id = ?", (promo_id,)).fetchone()
        return self._row_to_promo(row)

    def list(self, status: Optional[PromoStatus] = None) -> List[Promo]:
        query = "SELECT * FROM promos"
        params: tuple = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status.value,)
        query += " ORDER BY expiry_date ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_promo(r) for r in rows]

    def update_status(self, promo_id: int, status: PromoStatus) -> Optional[Promo]:
        with self._connect() as conn:
            conn.execute(
                "UPDATE promos SET status = ? WHERE id = ?", (status.value, promo_id)
            )
            row = conn.execute("SELECT * FROM promos WHERE id = ?", (promo_id,)).fetchone()
        return self._row_to_promo(row) if row else None

    def delete(self, promo_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM promos WHERE id = ?", (promo_id,))
        return cur.rowcount > 0
