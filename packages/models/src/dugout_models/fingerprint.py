"""Manager tactical fingerprint and player tactical fit.

What free data allows (see docs/methods): true PPDA, field tilt, pass length, width, directness and build-up
speed need event data, which is only open for old seasons. For current managers we build a *proxy* fingerprint
from Opta-derived FPL team aggregates available for every Premier League match since 2022-23:

  threat_share      team share of FPL "threat" (Opta: dangerous-area involvement)      ~ field tilt / territory
  creativity_share  team share of "creativity" (chance-creating passes)                 ~ possession-based creation
  influence_share   team share of "influence" (overall involvement)                     ~ control of the game
  xg_for, xg_against per match                                                           ~ attacking / defensive output
  xg_per_threat     xG created per unit of threat                                        ~ shot selection / directness
  def_actions       tackles + clearances/blocks/interceptions + recoveries per match     ~ defensive intensity (2025-26+)

A manager's fingerprint = match-weighted mean over the Premier League matches he managed (Wikidata spells).
Tactical fit of a player for a manager at a position = cosine similarity between the player's per-90 profile
and the profile of players that manager has given the most minutes to in that position, mapped to 0-100.
Validation: for players who joined a club, does fit (with the manager's prior profile) predict minutes share?
"""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.preprocessing import StandardScaler

from dugout_models.roles import BASE, season_profiles

STYLE = [
    "threat_share",
    "creativity_share",
    "influence_share",
    "xg_for",
    "xg_against",
    "xg_per_threat",
    "def_actions",
]


def team_matches(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per team per match with the proxy style metrics."""
    df = con.execute(
        """
        WITH t AS (
            SELECT s.match_id, s.club_id, sum(s.threat) AS threat, sum(s.creativity) AS creativity,
                   sum(s.influence) AS influence, sum(s.xg) AS xg,
                   sum(coalesce(s.tackles, 0) + coalesce(s.cbi, 0) + coalesce(s.recoveries, 0)) AS def_actions,
                   count(s.tackles) AS def_rows
            FROM player_match_stats s WHERE s.source IN ('fpl_history', 'fpl') GROUP BY 1, 2
        )
        SELECT a.match_id, a.club_id, CAST(m.kickoff_utc AS DATE) AS date, m.season,
               a.threat / nullif(a.threat + b.threat, 0) AS threat_share,
               a.creativity / nullif(a.creativity + b.creativity, 0) AS creativity_share,
               a.influence / nullif(a.influence + b.influence, 0) AS influence_share,
               a.xg AS xg_for, b.xg AS xg_against, a.xg / nullif(a.threat, 0) * 100 AS xg_per_threat,
               CASE WHEN a.def_rows > 0 THEN a.def_actions END AS def_actions
        FROM t a JOIN t b ON a.match_id = b.match_id AND a.club_id <> b.club_id
        JOIN matches m ON m.match_id = a.match_id
        """
    ).df()
    df["date"] = pd.to_datetime(df.date)
    return df


def attribute_managers(tm: pd.DataFrame, tenures: pd.DataFrame) -> pd.DataFrame:
    """Adds manager_id/name to each team-match from Wikidata spells (latest spell that covers the date)."""
    t = tenures.copy()
    t["start_date"] = pd.to_datetime(t.start_date)
    t["end_date"] = pd.to_datetime(t.end_date).fillna(pd.Timestamp("2100-01-01"))
    out = tm.merge(t[["club_id", "manager_id", "name", "start_date", "end_date"]], on="club_id", how="left")
    out = out[(out.date >= out.start_date) & (out.date <= out.end_date)]
    return out.sort_values("start_date").drop_duplicates(["match_id", "club_id"], keep="last")


def manager_fingerprints(con: duckdb.DuckDBPyConnection, before: pd.Timestamp | None = None) -> pd.DataFrame:
    tm = team_matches(con)
    if before is not None:
        tm = tm[tm.date < before]
    tenures = con.execute("SELECT * FROM manager_tenures").df()
    am = attribute_managers(tm, tenures)
    fp = (
        am.groupby(["manager_id", "name"])
        .agg(matches=("match_id", "nunique"), **{c: (c, "mean") for c in STYLE})
        .reset_index()
    )
    z = StandardScaler().fit_transform(fp[STYLE].fillna(fp[STYLE].mean()))
    for i, c in enumerate(STYLE):
        fp[f"z_{c}"] = z[:, i]
    return fp


def required_profiles(con: duckdb.DuckDBPyConnection, min_minutes: int = 900) -> pd.DataFrame:
    """Per manager and position: minutes-weighted mean per-90 profile of the players he used."""
    prof = season_profiles(con, min_minutes)
    tm = team_matches(con)
    tenures = con.execute("SELECT * FROM manager_tenures").df()
    am = attribute_managers(tm, tenures)
    # the manager of a club-season = the one in charge for most of its matches
    main = (
        am.groupby(["club_id", "season", "manager_id"])
        .size()
        .rename("n")
        .reset_index()
        .sort_values("n")
        .drop_duplicates(["club_id", "season"], keep="last")
    )
    p = prof.merge(main[["club_id", "season", "manager_id"]], on=["club_id", "season"])
    w = p.minutes
    return (
        p.assign(**{c: p[c] * w for c in BASE}, w=w)
        .groupby(["manager_id", "position"])[[*BASE, "w"]]
        .sum()
        .pipe(lambda d: d[BASE].div(d.w, axis=0))
        .reset_index()
    )


def fit_scores(
    players: pd.DataFrame, required: pd.DataFrame, manager_id: str, scaler: StandardScaler
) -> pd.Series:
    """0-100 fit of each player (per-90 BASE profile) to the manager's required profile at his position."""
    req = required[required.manager_id == manager_id].set_index("position")
    out = pd.Series(np.nan, index=players.index)
    for pos, grp in players.groupby("position"):
        if pos not in req.index:
            continue
        a = scaler.transform(grp[BASE])
        b = scaler.transform(req.loc[[pos], BASE])[0]
        cos = (a @ b) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b) + 1e-12)
        out.loc[grp.index] = (cos + 1) * 50
    return out


def backtest(con: duckdb.DuckDBPyConnection, out_dir: Path | None = None) -> dict:
    """Players who changed club between consecutive seasons: does fit with the new manager's profile (built from
    the *previous* season only) correlate with the minutes share they then got?"""
    prof = season_profiles(con, 0)
    prof = prof.dropna(subset=BASE)
    scaler = StandardScaler().fit(prof[BASE])
    tm = team_matches(con)
    tenures = con.execute("SELECT * FROM manager_tenures").df()
    am = attribute_managers(tm, tenures)
    main = (
        am.groupby(["club_id", "season", "manager_id"])
        .size()
        .rename("n")
        .reset_index()
        .sort_values("n")
        .drop_duplicates(["club_id", "season"], keep="last")
    )
    seasons = sorted(prof.season.unique())
    rows = []
    for prev, cur in itertools.pairwise(seasons):
        a = prof[(prof.season == prev) & (prof.minutes >= 900)]
        b = prof[prof.season == cur]
        movers = a.merge(b[["player_id", "club_id", "minutes"]], on="player_id", suffixes=("", "_new"))
        movers = movers[movers.club_id != movers.club_id_new]
        mgr = main[main.season == cur].set_index("club_id").manager_id
        # required profiles from seasons before `cur` only
        hist = prof[prof.season < cur].merge(
            main[["club_id", "season", "manager_id"]], on=["club_id", "season"]
        )
        hist = hist[hist.minutes >= 900]
        req = (
            hist.assign(**{c: hist[c] * hist.minutes for c in BASE})
            .groupby(["manager_id", "position"])[[*BASE, "minutes"]]
            .sum()
        )
        req = req[BASE].div(req.minutes, axis=0).reset_index()
        club_matches = tm[tm.season == cur].groupby("club_id").match_id.nunique()
        for r in movers.itertuples():
            m = mgr.get(r.club_id_new)
            if m is None or not ((req.manager_id == m) & (req.position == r.position)).any():
                continue
            one = movers.loc[[r.Index]]
            fit = fit_scores(one, req, m, scaler).iloc[0]
            share = r.minutes_new / (90 * club_matches.get(r.club_id_new, 38))
            rows.append(
                {"season": cur, "player_id": r.player_id, "fit": fit, "minutes_share": min(share, 1.0)}
            )
    res = pd.DataFrame(rows)
    rho, pval = spearmanr(res.fit, res.minutes_share) if len(res) > 5 else (np.nan, np.nan)
    fp = manager_fingerprints(con)
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "movers": len(res),
        "spearman_fit_vs_minutes_share": float(rho),
        "p_value": float(pval),
        "managers_fingerprinted": int((fp.matches >= 10).sum()),
    }
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "fingerprint.json").write_text(json.dumps(report, indent=2))
        top = fp[fp.matches >= 38].sort_values("threat_share", ascending=False)
        lines = [
            "# Manager fingerprint and tactical fit",
            "",
            f"Generated {report['generated_at']}.",
            "",
            "Proxy style metrics from Opta-derived FPL team aggregates (every PL match since 2022-23); manager "
            "spells from Wikidata. True PPDA / field tilt / pass length / width need event data, which is not "
            "freely available for current seasons.",
            "",
            "## Does tactical fit predict playing time?",
            "",
            f"Players who changed club: {report['movers']}. Spearman correlation between fit (new manager's "
            f"profile, built only from earlier seasons) and the minutes share they then got: "
            f"**{rho:.2f}** (p = {pval:.3g}).",
            "",
            "## Managers with at least 38 PL matches since 2022-23, by territorial dominance",
            "",
            "| Manager | Matches | Threat share | Creativity share | xG for | xG against | xG per 100 threat |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in top.itertuples():
            lines.append(
                f"| {r.name} | {r.matches} | {r.threat_share:.1%} | {r.creativity_share:.1%} | "
                f"{r.xg_for:.2f} | {r.xg_against:.2f} | {r.xg_per_threat:.2f} |"
            )
        (out_dir / "fingerprint.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
