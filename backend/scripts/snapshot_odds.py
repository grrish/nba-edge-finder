#!/usr/bin/env python3
"""Append one odds snapshot (one row per game x bookmaker) to odds_history.db.

Calls OddsService.get_nba_game_lines_by_bookmaker(), which shares a cache
with the existing get_nba_game_lines() the app already calls — running this
makes at most one Odds API call (zero if the app already fetched within the
last 30 minutes; see odds.py's _TTL_LINES). Append-only, no dedupe: run it
as many times as you like to build up a price-movement history.

Usage (from backend/):
    python scripts/snapshot_odds.py
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_settings  # noqa: E402
from services.odds import OddsService  # noqa: E402
from services.odds_history_db import OddsHistoryStore  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s  %(message)s")

    settings = get_settings()
    store = OddsHistoryStore(OddsHistoryStore.resolve_path(settings.odds_history_db_path))
    odds = OddsService()

    fetched_at = datetime.now(timezone.utc).isoformat()
    bookmaker_rows = odds.get_nba_game_lines_by_bookmaker()

    rows = [{**r, "fetched_at": fetched_at} for r in bookmaker_rows]
    written = store.append_many(rows)

    print(f"Wrote {written} row(s) to {store._path} (fetched_at={fetched_at})")
    print(f"Total rows in store: {store.total_count()}")


if __name__ == "__main__":
    main()
