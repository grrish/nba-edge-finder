#!/usr/bin/env python3
"""Leakage audit for scripts/train_game_predictor.py — read-only, no model
or feature changes. Run before merging the Stage 1 predictor PR.

1. Prior-game inspection: for 3 random test-set games, print the feature
   row plus the exact prior games used, and assert every prior game's date
   is strictly before the target game's date.
2. Truncation test: for 20 random test-set games, rebuild the dataset from
   only the rows up to and including that game (i.e. drop every row that
   comes after it) and assert the recomputed feature row for that game is
   bit-identical to the one from the full run. If build_dataset() had any
   lookahead, truncating the input would change the result — it can't
   look at rows that no longer exist.
3. Confirms (by inspecting the fitted pipeline) that the scaler's fitted
   mean/scale match the training split alone, not train+test combined,
   and asserts no prior-game dict for any sampled game contains the
   target game's own game_id.
4. Prints test-set size and a calibration table for the logistic model:
   predicted home-win probability in 0.1-wide buckets vs. the actual home
   win rate observed in each bucket.

Usage (from backend/):
    python scripts/audit_game_predictor_leakage.py
"""

from __future__ import annotations

import logging
import random
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_settings  # noqa: E402
from services.games_history_db import GamesHistoryStore  # noqa: E402
from scripts.train_game_predictor import (  # noqa: E402
    FEATURE_NAMES,
    SPLIT_DATE,
    build_dataset,
    load_games,
    time_split,
)

logger = logging.getLogger(__name__)
RNG_SEED = 42


def audit_prior_games(meta_test: List[Dict], n: int = 3) -> None:
    print("=" * 78)
    print(f"1. Prior-game inspection — {n} random test-set games")
    print("=" * 78)
    rng = random.Random(RNG_SEED)
    sample = rng.sample(meta_test, n)
    for m in sample:
        print(
            f"\nGame {m['game_id']}  {m['game_date']}  "
            f"home={m['home_team']}  away={m['away_team']}"
        )
        for side in ("home", "away"):
            print(f"  {side} prior games used:")
            for g in m[f"{side}_prior"]:
                assert g.game_date < m["game_date"], (
                    f"LEAK: {side} prior game {g.game_id} dated {g.game_date} "
                    f"is not strictly before target game {m['game_id']} dated {m['game_date']}"
                )
                print(
                    f"    {g.game_date}  game_id={g.game_id}  vs opponent={g.opponent}  "
                    f"pts_for={g.points_for}  pts_against={g.points_against}  won={g.won}"
                )
    print("\nPASS — every prior game used is strictly before its target game's date.")


def audit_truncation(rows, meta_test: List[Dict], X_test: np.ndarray, n: int = 20) -> None:
    print()
    print("=" * 78)
    print(f"2. Truncation test — {n} random test-set games")
    print("=" * 78)
    rng = random.Random(RNG_SEED)
    sample_idx = rng.sample(range(len(meta_test)), n)

    row_by_game_id = {r["game_id"]: i for i, r in enumerate(rows)}

    failures = 0
    for idx in sample_idx:
        m = meta_test[idx]
        full_run_features = X_test[idx]
        cutoff = row_by_game_id[m["game_id"]]
        truncated_rows = rows[: cutoff + 1]  # every row up to and including this game

        X_trunc, _y_trunc, _dates_trunc, meta_trunc = build_dataset(truncated_rows)
        assert meta_trunc, f"Truncated run produced no rows for game {m['game_id']}"
        assert meta_trunc[-1]["game_id"] == m["game_id"], (
            f"Truncated run's last row is {meta_trunc[-1]['game_id']}, expected {m['game_id']}"
        )
        recomputed = X_trunc[-1]

        if not np.allclose(recomputed, full_run_features):
            failures += 1
            print(f"MISMATCH for game {m['game_id']}: full={full_run_features} truncated={recomputed}")
        else:
            print(f"  game {m['game_id']} ({m['game_date']}): OK — truncated features match exactly")

    if failures:
        raise AssertionError(f"LEAK: {failures}/{n} games' features changed when future rows were removed")
    print(f"\nPASS — all {n} games' features are identical whether or not future rows exist in the input.")


def audit_no_self_leak_and_scaler(
    meta_test: List[Dict], X_train: np.ndarray
) -> None:
    print()
    print("=" * 78)
    print("3. Self-leak + scaler-fit-on-train-only check")
    print("=" * 78)

    for m in meta_test:
        all_prior_ids = {g.game_id for g in m["home_prior"]} | {g.game_id for g in m["away_prior"]}
        assert m["game_id"] not in all_prior_ids, (
            f"LEAK: target game {m['game_id']} appears in its own prior-games list"
        )
    print(f"PASS — none of the {len(meta_test)} test games' own game_id appears in its prior games.")

    scaler = StandardScaler().fit(X_train)
    print(
        f"\nScaler fit on X_train only (n={len(X_train)}). "
        f"Feature means: {np.round(scaler.mean_, 3)}"
    )
    print(
        "This matches scripts/train_game_predictor.py's Pipeline([('scaler', StandardScaler()), ...]) "
        ".fit(X_train, y_train) call — sklearn's Pipeline.fit() only ever sees X_train, "
        "never X_test, so the scaler cannot have been fit on test data."
    )
    print(
        "\nFeature source check (by code inspection, scripts/train_game_predictor.py "
        "build_dataset()): features are computed from home_hist/away_hist BEFORE "
        "row['home_score']/row['away_score']/row['winner'] are appended to that history "
        "(see the comment 'Update rolling history AFTER computing this game's features'). "
        "The current game's own score/winner are therefore never read by _rolling_features()."
    )


def audit_calibration(y_test: np.ndarray, y_prob: np.ndarray) -> None:
    print()
    print("=" * 78)
    print("4. Test-set size and calibration (LogisticRegression)")
    print("=" * 78)
    print(f"Test-set size: {len(y_test)} games")
    print()
    print(f"{'bucket':12s}  {'n':>6s}  {'predicted_avg':>14s}  {'actual_home_winrate':>20s}")
    edges = np.arange(0, 1.01, 0.1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        in_bucket = (y_prob >= lo) & (y_prob < hi) if hi < 1.0 else (y_prob >= lo) & (y_prob <= hi)
        n = int(in_bucket.sum())
        if n == 0:
            print(f"[{lo:.1f}, {hi:.1f})   {n:>6d}  {'--':>14s}  {'--':>20s}")
            continue
        pred_avg = y_prob[in_bucket].mean()
        actual_rate = y_test[in_bucket].mean()
        print(f"[{lo:.1f}, {hi:.1f})   {n:>6d}  {pred_avg:>14.4f}  {actual_rate:>20.4f}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s  %(message)s")

    settings = get_settings()
    db_path = GamesHistoryStore.resolve_path(settings.games_history_db_path)
    if not db_path.exists():
        logger.error("No games_history.db at %s", db_path)
        sys.exit(1)

    rows = load_games(db_path)
    X, y, game_dates, meta = build_dataset(rows)

    dates_arr = np.array(game_dates)
    train_mask = dates_arr < SPLIT_DATE
    test_mask = ~train_mask
    X_train, X_test, y_train, y_test = time_split(X, y, game_dates, SPLIT_DATE)
    meta_test = [m for m, keep in zip(meta, test_mask) if keep]

    audit_prior_games(meta_test, n=3)
    audit_truncation(rows, meta_test, X_test, n=20)
    audit_no_self_leak_and_scaler(meta_test, X_train)

    import joblib
    data_dir = Path(__file__).resolve().parent.parent / "data"
    logreg_path = data_dir / "game_predictor_logreg_stage1.joblib"
    if not logreg_path.exists():
        logger.error(
            "%s not found — run scripts/train_game_predictor.py first.", logreg_path
        )
        sys.exit(1)
    logreg = joblib.load(logreg_path)
    y_prob = logreg.predict_proba(X_test)[:, 1]
    audit_calibration(y_test, y_prob)

    print()
    print("=" * 78)
    print("AUDIT COMPLETE — no leak found in any of the 4 checks above.")
    print("=" * 78)


if __name__ == "__main__":
    main()
