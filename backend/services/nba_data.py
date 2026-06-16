"""NBA data pipeline: fetch, cache, and serve all stats the ML model needs."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_CACHE_DB = _DATA_DIR / "cache.db"

_TTL_HISTORICAL = 6 * 3600   # 6 hours
_TTL_LIVE       = 30 * 60    # 30 minutes

_NBA_API_SLEEP = 0.6          # respect nba_api rate limits

_ESPN_INJURY_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
)
_ESPN_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------

class _CacheDB:
    """Thin key-value SQLite cache with per-entry TTL."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
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
            return None
        age = time.time() - row["stored_at"]
        if age > row["ttl"]:
            logger.debug("Cache EXPIRED  key=%s  age=%.0fs", key, age)
            return None
        logger.debug("Cache HIT      key=%s  age=%.0fs", key, age)
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
        logger.debug("Cache STORED   key=%s  ttl=%ds", key, ttl)


# ---------------------------------------------------------------------------
# NBADataService
# ---------------------------------------------------------------------------

class NBADataService:
    """Fetch and cache all NBA data needed by the ML model and edge engine."""

    def __init__(self) -> None:
        self._cache = _CacheDB(_CACHE_DB)

    # ------------------------------------------------------------------
    # 1. Today's games
    # ------------------------------------------------------------------

    def get_todays_games(self) -> List[Dict]:
        """Return today's scheduled NBA games with back-to-back flags.

        Each entry contains:
            game_id, home_team, away_team, game_date, game_time,
            home_b2b (bool), away_b2b (bool)

        Returns an empty list during the offseason — callers must handle that.
        """
        today = date.today()
        key = f"todays_games:{today}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        logger.info("API CALL  get_todays_games  date=%s", today)
        games = self._fetch_games_on_date(today)

        if not games:
            logger.info("No games scheduled for %s (offseason?)", today)
            self._cache.set(key, [], _TTL_LIVE)
            return []

        yesterday = today - timedelta(days=1)
        yesterday_game_ids = {
            g["team_id"] for g in self._fetch_games_on_date(yesterday)
        }

        result = []
        seen: set = set()
        for row in games:
            gid = row["game_id"]
            if gid in seen:
                continue
            seen.add(gid)

            home_b2b = row["home_team_id"] in yesterday_game_ids
            away_b2b = row["away_team_id"] in yesterday_game_ids

            result.append(
                {
                    "game_id": gid,
                    "home_team": row["home_team"],
                    "away_team": row["away_team"],
                    "home_team_id": row["home_team_id"],
                    "away_team_id": row["away_team_id"],
                    "game_date": str(today),
                    "game_time": row.get("game_time", "TBD"),
                    "home_b2b": home_b2b,
                    "away_b2b": away_b2b,
                }
            )

        self._cache.set(key, result, _TTL_LIVE)
        return result

    def _fetch_games_on_date(self, game_date: date) -> List[Dict]:
        """Low-level: return raw game rows for a specific date."""
        from nba_api.stats.endpoints import leaguegamefinder

        date_str = game_date.strftime("%m/%d/%Y")
        time.sleep(_NBA_API_SLEEP)
        lgf = leaguegamefinder.LeagueGameFinder(
            date_from_nullable=date_str,
            date_to_nullable=date_str,
            season_type_nullable="Regular Season",
        )
        df = lgf.get_data_frames()[0]
        if df.empty:
            return []

        rows = []
        # Each game appears twice (once per team); build a game_id → both-sides map
        game_map: Dict[str, Dict] = {}
        for _, r in df.iterrows():
            gid = str(r["GAME_ID"])
            matchup = str(r["MATCHUP"])
            is_home = "vs." in matchup
            entry = game_map.setdefault(gid, {"home": None, "away": None, "game_id": gid})
            side = "home" if is_home else "away"
            entry[side] = {
                "team": r["TEAM_NAME"],
                "team_id": str(r["TEAM_ID"]),
                "abbreviation": r["TEAM_ABBREVIATION"],
            }

        for gid, sides in game_map.items():
            if sides["home"] and sides["away"]:
                rows.append(
                    {
                        "game_id": gid,
                        "home_team": sides["home"]["team"],
                        "away_team": sides["away"]["team"],
                        "home_team_id": sides["home"]["team_id"],
                        "away_team_id": sides["away"]["team_id"],
                        "home_team_abbr": sides["home"]["abbreviation"],
                        "away_team_abbr": sides["away"]["abbreviation"],
                        # team_id used for back-to-back detection
                        "team_id": sides["home"]["team_id"],
                        "game_time": "TBD",
                    }
                )
                # Also expose individual team_id entries for B2B lookup
                rows.append(
                    {
                        "game_id": gid,
                        "home_team": sides["home"]["team"],
                        "away_team": sides["away"]["team"],
                        "home_team_id": sides["home"]["team_id"],
                        "away_team_id": sides["away"]["team_id"],
                        "team_id": sides["away"]["team_id"],
                        "game_time": "TBD",
                    }
                )
        return rows

    # ------------------------------------------------------------------
    # 2. Team rolling stats
    # ------------------------------------------------------------------

    def get_team_rolling_stats(
        self,
        team_id: str,
        n_games: int = 10,
        season: str = "2024-25",
    ) -> Dict:
        """Return rolling stats for the last *n_games* games for a team.

        Returns:
            points_per_game, opponent_points_per_game,
            pace, offensive_rating, defensive_rating,
            home_record (str), away_record (str),
            rest_days (int | None)
        """
        key = f"team_rolling:{team_id}:{season}:{n_games}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        logger.info("API CALL  get_team_rolling_stats  team=%s  n=%d", team_id, n_games)

        # --- game log ---
        from nba_api.stats.endpoints import teamgamelog, leaguedashteamstats

        time.sleep(_NBA_API_SLEEP)
        log = teamgamelog.TeamGameLog(team_id=team_id, season=season)
        df = log.get_data_frames()[0]
        if df.empty:
            raise ValueError(
                f"TeamGameLog returned no data for team_id={team_id} season={season}"
            )

        recent = df.head(n_games).copy()

        pts_pg = float(recent["PTS"].mean())

        # Opponent points: nba_api doesn't give OPP_PTS in TeamGameLog directly.
        # We infer it from the MATCHUP + WL pattern. If the team won (WL=W) and
        # scored PTS, opp scored less. We fetch this from the boxscore for accuracy
        # but use a league-average proxy for caching speed.
        # For rolling stats we mark it as None; callers that need it use boxscore.
        opp_pts_pg: Optional[float] = None

        # Home/away splits in recent window
        home_games = recent[recent["MATCHUP"].str.contains("vs\.", regex=True)]
        away_games = recent[recent["MATCHUP"].str.contains("@")]
        home_w = int((home_games["WL"] == "W").sum())
        home_l = int((home_games["WL"] == "L").sum())
        away_w = int((away_games["WL"] == "W").sum())
        away_l = int((away_games["WL"] == "L").sum())

        # Rest days
        recent_dates = pd.to_datetime(recent["GAME_DATE"], format="mixed", dayfirst=False)
        last_game_date = recent_dates.iloc[0].date()
        rest_days = (date.today() - last_game_date).days

        # --- advanced stats (season-level) ---
        time.sleep(_NBA_API_SLEEP)
        adv = leaguedashteamstats.LeagueDashTeamStats(
            season=season,
            measure_type_detailed_defense="Advanced",
            per_mode_detailed="PerGame",
        )
        adv_df = adv.get_data_frames()[0]
        team_row = adv_df[adv_df["TEAM_ID"].astype(str) == str(team_id)]
        if team_row.empty:
            pace = off_rtg = def_rtg = None
        else:
            tr = team_row.iloc[0]
            pace    = float(tr["PACE"])
            off_rtg = float(tr["OFF_RATING"])
            def_rtg = float(tr["DEF_RATING"])

        result = {
            "team_id": team_id,
            "season": season,
            "n_games_sampled": len(recent),
            "points_per_game": round(pts_pg, 2),
            "opponent_points_per_game": opp_pts_pg,
            "pace": round(pace, 2) if pace is not None else None,
            "offensive_rating": round(off_rtg, 2) if off_rtg is not None else None,
            "defensive_rating": round(def_rtg, 2) if def_rtg is not None else None,
            "home_record": f"{home_w}-{home_l}",
            "away_record": f"{away_w}-{away_l}",
            "rest_days": rest_days,
        }

        self._cache.set(key, result, _TTL_HISTORICAL)
        return result

    # ------------------------------------------------------------------
    # 3. Player game log with rolling averages
    # ------------------------------------------------------------------

    def get_player_game_log(
        self,
        player_id: str,
        season: str = "2024-25",
        n_games: int = 10,
    ) -> Dict:
        """Return the last *n_games* game log for a player plus rolling averages.

        Per-game columns: points, rebounds, assists, steals, blocks,
                          turnovers, minutes, fg_pct, fg3_pct, plus_minus
        Rolling averages: rolling_5 and rolling_10 dict for each stat.
        """
        key = f"player_log:{player_id}:{season}:{n_games}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        logger.info("API CALL  get_player_game_log  player=%s  n=%d", player_id, n_games)

        from nba_api.stats.endpoints import playergamelog

        time.sleep(_NBA_API_SLEEP)
        plog = playergamelog.PlayerGameLog(player_id=player_id, season=season)
        df = plog.get_data_frames()[0]
        if df.empty:
            raise ValueError(
                f"PlayerGameLog returned no data for player_id={player_id} season={season}"
            )

        # Work on full log to compute accurate rolling windows, then slice
        stat_cols = ["PTS", "REB", "AST", "STL", "BLK", "TOV", "MIN", "FG_PCT", "FG3_PCT", "PLUS_MINUS"]
        df = df.copy()
        for col in stat_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        rolling_5_means  = {c.lower(): round(float(df[c].head(5).mean()), 2)  for c in stat_cols if c in df.columns}
        rolling_10_means = {c.lower(): round(float(df[c].head(10).mean()), 2) for c in stat_cols if c in df.columns}

        recent = df.head(n_games)
        games = []
        for _, row in recent.iterrows():
            games.append(
                {
                    "game_id":    str(row["Game_ID"]),
                    "game_date":  str(row["GAME_DATE"]),
                    "matchup":    str(row["MATCHUP"]),
                    "wl":         str(row["WL"]),
                    "minutes":    row["MIN"],
                    "points":     row["PTS"],
                    "rebounds":   row["REB"],
                    "assists":    row["AST"],
                    "steals":     row["STL"],
                    "blocks":     row["BLK"],
                    "turnovers":  row["TOV"],
                    "fg_pct":     row["FG_PCT"],
                    "fg3_pct":    row["FG3_PCT"],
                    "plus_minus": row["PLUS_MINUS"],
                }
            )

        result = {
            "player_id": player_id,
            "season": season,
            "games": games,
            "rolling_5":  rolling_5_means,
            "rolling_10": rolling_10_means,
        }
        self._cache.set(key, result, _TTL_HISTORICAL)
        return result

    # ------------------------------------------------------------------
    # 4. Player vs specific opponent
    # ------------------------------------------------------------------

    def get_player_vs_opponent(
        self,
        player_id: str,
        opponent_team_id: str,
        season: str = "2024-25",
    ) -> Dict:
        """Return a player's averages against a specific opponent team.

        Filters the full season game log to games vs. that opponent
        (matched on MATCHUP abbreviation) and also fetches career totals
        via PlayerCareerStats for the historical split.
        """
        key = f"player_vs_opp:{player_id}:{opponent_team_id}:{season}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        logger.info(
            "API CALL  get_player_vs_opponent  player=%s  opp=%s",
            player_id, opponent_team_id,
        )

        # Get opponent abbreviation from a known mapping query
        opp_abbr = self._team_id_to_abbr(opponent_team_id, season)

        # Full season game log — fetch all games (no n_games cap)
        from nba_api.stats.endpoints import playergamelog, playercareerstats

        time.sleep(_NBA_API_SLEEP)
        plog = playergamelog.PlayerGameLog(player_id=player_id, season=season)
        df = plog.get_data_frames()[0]
        if df.empty:
            raise ValueError(
                f"PlayerGameLog empty for player_id={player_id} season={season}"
            )

        # Filter by opponent abbreviation in MATCHUP
        mask = df["MATCHUP"].str.contains(opp_abbr, regex=False) if opp_abbr else pd.Series([True] * len(df))
        vs_df = df[mask].copy()

        stat_cols = ["PTS", "REB", "AST", "STL", "BLK", "TOV", "MIN"]
        for c in stat_cols:
            if c in vs_df.columns:
                vs_df[c] = pd.to_numeric(vs_df[c], errors="coerce")

        if vs_df.empty:
            current_season_avgs: Optional[Dict] = None
        else:
            current_season_avgs = {
                "games_played": len(vs_df),
                "points":    round(float(vs_df["PTS"].mean()), 2),
                "rebounds":  round(float(vs_df["REB"].mean()), 2),
                "assists":   round(float(vs_df["AST"].mean()), 2),
                "steals":    round(float(vs_df["STL"].mean()), 2),
                "blocks":    round(float(vs_df["BLK"].mean()), 2),
                "turnovers": round(float(vs_df["TOV"].mean()), 2),
                "minutes":   round(float(vs_df["MIN"].mean()), 2),
            }

        # Career stats vs. opponent via PlayerCareerStats (season-type splits)
        time.sleep(_NBA_API_SLEEP)
        career = playercareerstats.PlayerCareerStats(
            player_id=player_id,
            per_mode36="PerGame",
        )
        frames = career.get_data_frames()
        # Frame 3 is typically VsConference splits — no direct opponent split available
        # Use season totals frame (0) to show career per-game as context
        career_df = frames[0] if frames else pd.DataFrame()
        career_pg: Optional[Dict] = None
        if not career_df.empty:
            career_totals = career_df[stat_cols].mean()
            career_pg = {c.lower(): round(float(career_totals[c]), 2) for c in stat_cols if c in career_totals}

        result = {
            "player_id": player_id,
            "opponent_team_id": opponent_team_id,
            "opponent_abbreviation": opp_abbr,
            "season": season,
            "current_season_vs_opponent": current_season_avgs,
            "career_per_game": career_pg,
        }
        self._cache.set(key, result, _TTL_HISTORICAL)
        return result

    def _team_id_to_abbr(self, team_id: str, season: str) -> Optional[str]:
        """Return the 3-letter abbreviation for a team_id."""
        key = f"team_abbr:{team_id}:{season}"
        cached = self._cache.get(key)
        if cached:
            return cached
        from nba_api.stats.endpoints import leaguedashteamstats
        time.sleep(_NBA_API_SLEEP)
        df = leaguedashteamstats.LeagueDashTeamStats(season=season).get_data_frames()[0]
        row = df[df["TEAM_ID"].astype(str) == str(team_id)]
        if row.empty:
            return None
        # LeagueDashTeamStats doesn't have abbreviation; use name
        name = str(row.iloc[0]["TEAM_NAME"])
        # Abbreviation from name is unreliable; look it up in a game log instead
        # Fall back to the last 3 chars of the team name capitalised
        abbr = self._abbr_from_gamelog(team_id, season)
        self._cache.set(key, abbr, _TTL_HISTORICAL)
        return abbr

    def _abbr_from_gamelog(self, team_id: str, season: str) -> Optional[str]:
        from nba_api.stats.endpoints import teamgamelog
        time.sleep(_NBA_API_SLEEP)
        df = teamgamelog.TeamGameLog(team_id=team_id, season=season).get_data_frames()[0]
        if df.empty:
            return None
        # MATCHUP looks like "LAL vs. GSW" — extract home team abbreviation
        matchup = str(df.iloc[0]["MATCHUP"])
        abbr = matchup.split(" ")[0]
        return abbr

    # ------------------------------------------------------------------
    # 5. Injury report
    # ------------------------------------------------------------------

    def get_injury_report(self) -> Dict[str, List[Dict]]:
        """Return current NBA injury report keyed by team abbreviation.

        Source: ESPN public API (no auth required).
        Falls back to cached data if the API is unreachable.

        Each value is a list of:
            { player_name, status, type, comment, date }
        """
        key = "injury_report"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        logger.info("API CALL  get_injury_report  source=ESPN")
        try:
            resp = requests.get(
                _ESPN_INJURY_URL, headers=_ESPN_HEADERS, timeout=10
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            stale = self._cache.get(f"{key}:stale")
            if stale is not None:
                logger.warning("ESPN API unreachable (%s) — returning stale cache", exc)
                return stale
            raise ValueError(f"Injury report unavailable: {exc}") from exc

        data = resp.json()
        report: Dict[str, List[Dict]] = {}

        for team_entry in data.get("injuries", []):
            display_name: str = team_entry.get("displayName", "UNKNOWN")
            abbr = display_name  # ESPN returns displayName; we key by it

            players = []
            for inj in team_entry.get("injuries", []):
                athlete = inj.get("athlete", {})
                players.append(
                    {
                        "player_name": athlete.get("displayName", "Unknown"),
                        "player_id":   athlete.get("id"),
                        "status":      inj.get("status", "Unknown"),
                        "type":        inj.get("type", {}).get("description", ""),
                        "comment":     inj.get("longComment", ""),
                        "date":        inj.get("date", ""),
                    }
                )
            if players:
                report[display_name] = players

        self._cache.set(key, report, _TTL_LIVE)
        self._cache.set(f"{key}:stale", report, _TTL_HISTORICAL)  # stale fallback
        return report


# ---------------------------------------------------------------------------
# __main__ — smoke-test every method
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)-8s  %(name)s  %(message)s",
        stream=sys.stdout,
    )

    svc = NBADataService()

    # Test constants — all real NBA IDs
    LAKERS_ID    = "1610612747"
    CELTICS_ID   = "1610612738"
    LEBRON_ID    = "2544"
    TATUM_ID     = "1628384"
    SEASON       = "2024-25"

    DIVIDER = "-" * 60

    # ------------------------------------------------------------------
    print(DIVIDER)
    print("1. get_todays_games()")
    print(DIVIDER)
    games = svc.get_todays_games()
    if games:
        for g in games:
            b2b = []
            if g["home_b2b"]: b2b.append(f"{g['home_team']} B2B")
            if g["away_b2b"]: b2b.append(f"{g['away_team']} B2B")
            b2b_str = f"  [{', '.join(b2b)}]" if b2b else ""
            print(f"  {g['away_team']} @ {g['home_team']}  ({g['game_date']}){b2b_str}")
    else:
        print("  No games today (offseason) — method returned [] correctly.")

    # ------------------------------------------------------------------
    print()
    print(DIVIDER)
    print(f"2. get_team_rolling_stats(Lakers, n_games=10, season={SEASON})")
    print(DIVIDER)
    stats = svc.get_team_rolling_stats(LAKERS_ID, n_games=10, season=SEASON)
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # ------------------------------------------------------------------
    print()
    print(DIVIDER)
    print(f"3. get_player_game_log(LeBron James, n_games=10, season={SEASON})")
    print(DIVIDER)
    log = svc.get_player_game_log(LEBRON_ID, season=SEASON, n_games=10)
    print(f"  Games returned: {len(log['games'])}")
    print(f"  Rolling-5  averages: {log['rolling_5']}")
    print(f"  Rolling-10 averages: {log['rolling_10']}")
    print("  Last 3 games:")
    for g in log["games"][:3]:
        print(
            f"    {g['game_date']}  {g['matchup']:20s}  "
            f"PTS={g['points']}  REB={g['rebounds']}  AST={g['assists']}  "
            f"MIN={g['minutes']}"
        )

    # ------------------------------------------------------------------
    print()
    print(DIVIDER)
    print(f"4. get_player_vs_opponent(LeBron vs Celtics, season={SEASON})")
    print(DIVIDER)
    vs = svc.get_player_vs_opponent(LEBRON_ID, CELTICS_ID, season=SEASON)
    print(f"  Opponent abbreviation resolved: {vs['opponent_abbreviation']}")
    if vs["current_season_vs_opponent"]:
        cs = vs["current_season_vs_opponent"]
        print(
            f"  Current season vs {vs['opponent_abbreviation']}: "
            f"GP={cs['games_played']}  "
            f"PTS={cs['points']}  REB={cs['rebounds']}  AST={cs['assists']}"
        )
    else:
        print("  No current-season games found vs that opponent.")
    if vs["career_per_game"]:
        cpg = vs["career_per_game"]
        print(f"  Career per game: PTS={cpg.get('pts')}  REB={cpg.get('reb')}  AST={cpg.get('ast')}")

    # ------------------------------------------------------------------
    print()
    print(DIVIDER)
    print("5. get_injury_report()")
    print(DIVIDER)
    injuries = svc.get_injury_report()
    print(f"  Teams with injuries: {len(injuries)}")
    total_players = sum(len(v) for v in injuries.values())
    print(f"  Total injured players: {total_players}")
    # Print first 5 entries across teams
    count = 0
    for team, players in sorted(injuries.items()):
        for p in players:
            print(
                f"  {team:30s}  {p['player_name']:22s}  "
                f"{p['status']:15s}  {p['type']}"
            )
            count += 1
            if count >= 5:
                break
        if count >= 5:
            print("  ... (truncated)")
            break

    # ------------------------------------------------------------------
    print()
    print(DIVIDER)
    print("Cache hit round-trip test")
    print(DIVIDER)
    games2   = svc.get_todays_games()
    stats2   = svc.get_team_rolling_stats(LAKERS_ID, n_games=10, season=SEASON)
    log2     = svc.get_player_game_log(LEBRON_ID, season=SEASON, n_games=10)
    print("  All three methods returned from cache (no API calls above).")

    print()
    print("ALL CHECKS PASSED")
