"""Model-ready tables built from the warehouse."""

from __future__ import annotations

import duckdb
import pandas as pd

from dugout_models.metrics import outcome


def matches(con: duckdb.DuckDBPyConnection, league: str = "premier_league") -> pd.DataFrame:
    """Every finished league match we know about, oldest first, with odds and xG where available.

    football-data.co.uk gives results + closing odds from 2015-16; the FPL history adds kickoff times and
    Opta xG from 2022-23; the live FPL feed adds the current season.
    """
    df = con.execute(
        """
        WITH obs_xg AS (
            SELECT match_id, max(home_xg) AS home_xg, max(away_xg) AS away_xg
            FROM match_observations WHERE source IN ('fpl_history', 'api_football') GROUP BY match_id
        ), fpl_xg AS (   -- current season: team xG = sum of player xG (FPL live)
            SELECT s.match_id,
                   sum(s.xg) FILTER (WHERE s.club_id = m.home_club_id) AS home_xg,
                   sum(s.xg) FILTER (WHERE s.club_id = m.away_club_id) AS away_xg
            FROM player_match_stats s JOIN matches m USING (match_id)
            WHERE s.source = 'fpl' GROUP BY s.match_id
        ), base AS (
            SELECT h.season, h.date, h.home, h.away, h.home_goals, h.away_goals,
                   h.odds_home, h.odds_draw, h.odds_away
            FROM historical_results h WHERE h.league = ? AND h.home_goals IS NOT NULL
            UNION ALL   -- current-season matches not yet in football-data.co.uk
            SELECT m.season, CAST(m.kickoff_utc AS DATE), m.home_club_id, m.away_club_id, m.home_goals, m.away_goals,
                   NULL, NULL, NULL
            FROM matches m
            WHERE m.league = ? AND m.status = 'finished' AND NOT EXISTS (
                SELECT 1 FROM historical_results h
                WHERE h.season = m.season AND h.home = m.home_club_id AND h.away = m.away_club_id)
        )
        SELECT b.*, m.kickoff_utc, coalesce(o.home_xg, f.home_xg) AS home_xg, coalesce(o.away_xg, f.away_xg) AS away_xg,
               ? || ':' || b.season || ':' || b.home || ':' || b.away AS match_id
        FROM base b
        LEFT JOIN matches m ON m.match_id = ? || ':' || b.season || ':' || b.home || ':' || b.away
        LEFT JOIN obs_xg o ON o.match_id = m.match_id
        LEFT JOIN fpl_xg f ON f.match_id = m.match_id
        ORDER BY b.date, b.home
        """,
        [league, league, league, league],
    ).df()
    df["date"] = pd.to_datetime(df["date"])
    df["result"] = outcome(df["home_goals"], df["away_goals"])
    return df.reset_index(drop=True)


def player_minutes(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Per player-match minutes/starts/xG/xA for the missing-player feature (FPL history + live FPL)."""
    return con.execute(
        """SELECT s.match_id, s.club_id, s.player_id, s.minutes, s.starts,
                  coalesce(s.xg, 0) AS xg, coalesce(s.xa, 0) AS xa
           FROM player_match_stats s WHERE s.source IN ('fpl_history', 'fpl') AND s.starts IS NOT NULL"""
    ).df()
