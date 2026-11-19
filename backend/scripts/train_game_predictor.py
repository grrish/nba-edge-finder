#!/usr/bin/env python3
"""Stage 1 of a real game predictor: offline training and evaluation only.

Does NOT wire anything into EdgeEngine / find_game_edges — edge_engine.py's
model_prob = 0.5 placeholder is untouched (see
.claude/skills/expert/references/decision-predictor-ml-integration.md).
This script only trains and reports metrics for a candidate model; nothing
here is loaded by the app.

Reads backend/data/games_history.db (Settings.games_history_db_path).
Built with scikit-learn only — xgboost is in requirements.txt but fails to
import on this machine (its native lib needs libomp, not installed here),
so this trains a LogisticRegression and a GradientBoostingClassifier
instead, both from scikit-learn (no new dependency).

Leakage control: features for a given game are computed only from each
team's games strictly before it, walked in chronological order. Games with
a NULL game_type (an import where the source CSV had no type, or none was
mapped) are used only to build that rolling history — never as a training
or test target.

Targets are restricted to game_type in TARGET_GAME_TYPES (regular-season
and in-season-tournament games). A game is skipped as a target unless BOTH
teams already have >=10 prior games in their history.

Time-based split (never random): train on game_date < SPLIT_DATE, test on
game_date >= SPLIT_DATE.

Saves the fitted pipelines to backend/data/ (gitignored via the existing
backend/data/*.joblib rule) so this script can be re-run without retraining
being the only way to get the model back, but nothing loads them yet.

Usage (from backend/):
    python scripts/train_game_predictor.py
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_settings  # noqa: E402
from services.games_history_db import GamesHistoryStore  # noqa: E402

logger = logging.getLogger(__name__)

TARGET_GAME_TYPES = {"Regular Season", "Emirates NBA Cup", "NBA Emirates Cup", "NBA Cup"}
NBA_LEAGUE_ID = "00"
MIN_PRIOR_GAMES = 10
SPLIT_DATE = date(2025, 10, 1)

FEATURE_NAMES = [
    "home_last10_ppg", "home_last10_papg", "home_last10_winrate", "home_rest_days",
    "away_last10_ppg", "away_last10_papg", "away_last10_winrate", "away_rest_days",
]


@dataclass
class TeamGame:
    game_date: date
    points_for: int
    points_against: int
    won: bool
    game_id: str
    opponent: str


def load_games(db_path: Path) -> List[sqlite3.Row]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT game_id, season, league_id, game_date, home_team, away_team,
               home_score, away_score, winner, game_type
        FROM games
        WHERE league_id = ?
        ORDER BY game_date ASC, game_id ASC
        """,
        (NBA_LEAGUE_ID,),
    ).fetchall()
    conn.close()
    return rows


def _rolling_features(history: Deque[TeamGame], as_of: date) -> Tuple[float, float, float, int]:
    """last10 points-for avg, points-against avg, win rate, and days of rest."""
    recent = list(history)[-MIN_PRIOR_GAMES:]
    ppg = sum(g.points_for for g in recent) / len(recent)
    papg = sum(g.points_against for g in recent) / len(recent)
    winrate = sum(1 for g in recent if g.won) / len(recent)
    rest_days = (as_of - history[-1].game_date).days
    return ppg, papg, winrate, rest_days


def build_dataset(
    rows: List[sqlite3.Row],
) -> Tuple[np.ndarray, np.ndarray, List[date], List[Dict]]:
    """Walk games chronologically, building per-team rolling history as we go.

    Every game updates history (including NULL-game_type rows — warm-up
    only). Only games with game_type in TARGET_GAME_TYPES, where both teams
    already have >= MIN_PRIOR_GAMES prior entries, become (X, y) rows.

    Also returns *meta*, one dict per (X, y) row, carrying the game_id and
    the exact prior-game snapshots (TeamGame, pre-update) each side's
    features were computed from — used by the leakage audit, not training.
    """
    history: Dict[str, Deque[TeamGame]] = defaultdict(deque)
    X: List[List[float]] = []
    y: List[int] = []
    game_dates: List[date] = []
    meta: List[Dict] = []
    skipped_insufficient_history = 0
    skipped_wrong_type = 0

    for row in rows:
        game_date = date.fromisoformat(row["game_date"])
        home, away = row["home_team"], row["away_team"]
        home_score, away_score = row["home_score"], row["away_score"]

        if home_score is None or away_score is None:
            continue

        home_hist, away_hist = history[home], history[away]
        is_target_type = row["game_type"] in TARGET_GAME_TYPES
        has_enough_history = len(home_hist) >= MIN_PRIOR_GAMES and len(away_hist) >= MIN_PRIOR_GAMES

        if is_target_type and not has_enough_history:
            skipped_insufficient_history += 1
        elif not is_target_type:
            skipped_wrong_type += 1

        if is_target_type and has_enough_history:
            h_ppg, h_papg, h_wr, h_rest = _rolling_features(home_hist, game_date)
            a_ppg, a_papg, a_wr, a_rest = _rolling_features(away_hist, game_date)
            X.append([h_ppg, h_papg, h_wr, h_rest, a_ppg, a_papg, a_wr, a_rest])
            y.append(1 if row["winner"] == "home" else 0)
            game_dates.append(game_date)
            meta.append(
                {
                    "game_id": row["game_id"],
                    "game_date": game_date,
                    "home_team": home,
                    "away_team": away,
                    # Snapshot BEFORE this game is appended below — the
                    # exact prior games the features above were computed from.
                    "home_prior": list(home_hist)[-MIN_PRIOR_GAMES:],
                    "away_prior": list(away_hist)[-MIN_PRIOR_GAMES:],
                }
            )

        # Update rolling history AFTER computing this game's features, from
        # every game regardless of game_type (warm-up rows included).
        home_hist.append(
            TeamGame(game_date, home_score, away_score, row["winner"] == "home", row["game_id"], away)
        )
        away_hist.append(
            TeamGame(game_date, away_score, home_score, row["winner"] == "away", row["game_id"], home)
        )

    logger.info(
        "Built %d training examples (skipped %d non-target-type rows, "
        "%d target-type rows with insufficient history)",
        len(X), skipped_wrong_type, skipped_insufficient_history,
    )
    return np.array(X), np.array(y), game_dates, meta


def time_split(
    X: np.ndarray, y: np.ndarray, game_dates: List[date], split_date: date
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    dates_arr = np.array(game_dates)
    train_mask = dates_arr < split_date
    test_mask = ~train_mask
    return X[train_mask], X[test_mask], y[train_mask], y[test_mask]


def evaluate(name: str, y_true: np.ndarray, y_prob: np.ndarray) -> Dict[str, float]:
    y_prob = np.clip(y_prob, 1e-15, 1 - 1e-15)
    y_pred = (y_prob >= 0.5).astype(int)
    return {
        "model": name,
        "accuracy": accuracy_score(y_true, y_pred),
        "log_loss": log_loss(y_true, y_prob, labels=[0, 1]),
        "brier_score": brier_score_loss(y_true, y_prob),
    }


def print_metrics_table(results: List[Dict[str, float]]) -> None:
    print()
    print(f"{'model':30s}  {'accuracy':>10s}  {'log_loss':>10s}  {'brier_score':>12s}")
    print("-" * 68)
    for r in results:
        print(f"{r['model']:30s}  {r['accuracy']:>10.4f}  {r['log_loss']:>10.4f}  {r['brier_score']:>12.4f}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s  %(message)s")

    settings = get_settings()
    db_path = GamesHistoryStore.resolve_path(settings.games_history_db_path)
    if not db_path.exists():
        logger.error("No games_history.db at %s — run scripts/backfill_games.py first.", db_path)
        sys.exit(1)

    rows = load_games(db_path)
    logger.info("Loaded %d NBA rows from %s", len(rows), db_path)

    X, y, game_dates, _meta = build_dataset(rows)
    if len(X) == 0:
        logger.error("No eligible training examples — check TARGET_GAME_TYPES / history depth.")
        sys.exit(1)

    X_train, X_test, y_train, y_test = time_split(X, y, game_dates, SPLIT_DATE)
    logger.info(
        "Train: %d games (before %s)  Test: %d games (from %s)",
        len(X_train), SPLIT_DATE, len(X_test), SPLIT_DATE,
    )
    if len(X_test) == 0 or len(X_train) == 0:
        logger.error("Empty train or test split — not enough data on one side of %s.", SPLIT_DATE)
        sys.exit(1)

    results: List[Dict[str, float]] = []

    # --- Baseline 1: always pick home -----------------------------------
    always_home_prob = np.full(len(y_test), 1.0)
    results.append(evaluate("baseline: always home", y_test, always_home_prob))

    # --- Baseline 2: training-set home win rate --------------------------
    train_home_winrate = y_train.mean()
    constant_prob = np.full(len(y_test), train_home_winrate)
    results.append(evaluate("baseline: train home win rate", y_test, constant_prob))

    # --- Model 1: LogisticRegression (scaled) -----------------------------
    logreg = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000)),
    ])
    logreg.fit(X_train, y_train)
    logreg_prob = logreg.predict_proba(X_test)[:, 1]
    results.append(evaluate("LogisticRegression", y_test, logreg_prob))

    # --- Model 2: GradientBoostingClassifier ------------------------------
    gbc = GradientBoostingClassifier(random_state=0)
    gbc.fit(X_train, y_train)
    gbc_prob = gbc.predict_proba(X_test)[:, 1]
    results.append(evaluate("GradientBoostingClassifier", y_test, gbc_prob))

    print_metrics_table(results)

    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(logreg, data_dir / "game_predictor_logreg_stage1.joblib")
    joblib.dump(gbc, data_dir / "game_predictor_gbc_stage1.joblib")
    logger.info("Saved both fitted models to %s (gitignored, not committed)", data_dir)


if __name__ == "__main__":
    main()
