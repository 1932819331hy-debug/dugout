"""Pre-match features. Every value for a match uses only information dated strictly before kick-off.

The one deliberate exception is `missing_*`, which uses the *announced* starting XI (known ~1 h before kick-off):
it powers the lineup-informed variant and is excluded from the pre-lineup model.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dugout_models.dixon_coles import fit_map

ROLL = (5, 10)


def team_long(m: pd.DataFrame) -> pd.DataFrame:
    """One row per team per match."""
    pts_h = np.select([m.home_goals > m.away_goals, m.home_goals == m.away_goals], [3, 1], 0)
    pts_a = np.select([m.away_goals > m.home_goals, m.home_goals == m.away_goals], [3, 1], 0)
    home = pd.DataFrame(
        {
            "row": m.index,
            "date": m.date,
            "team": m.home,
            "gf": m.home_goals,
            "ga": m.away_goals,
            "xgf": m.home_xg,
            "xga": m.away_xg,
            "pts": pts_h,
            "side": "home",
        }
    )
    away = pd.DataFrame(
        {
            "row": m.index,
            "date": m.date,
            "team": m.away,
            "gf": m.away_goals,
            "ga": m.home_goals,
            "xgf": m.away_xg,
            "xga": m.home_xg,
            "pts": pts_a,
            "side": "away",
        }
    )
    return pd.concat([home, away]).sort_values(["team", "date", "row"]).reset_index(drop=True)


def rolling_form(m: pd.DataFrame) -> pd.DataFrame:
    t = team_long(m)
    g = t.groupby("team", group_keys=False)
    for n in ROLL:
        for col in ("gf", "ga", "pts"):
            t[f"{col}_l{n}"] = g[col].transform(lambda s, n=n: s.shift(1).rolling(n, min_periods=3).mean())
        for col in ("xgf", "xga"):  # xG only exists from 2022-23; require real observations
            t[f"{col}_l{n}"] = g[col].transform(lambda s, n=n: s.shift(1).rolling(n, min_periods=3).mean())
    t["rest_days"] = g["date"].transform(lambda s: s.diff().dt.days).clip(upper=21)
    cols = [c for c in t.columns if c.endswith(tuple(f"_l{n}" for n in ROLL))] + ["rest_days"]
    wide = []
    for side in ("home", "away"):
        part = t[t.side == side].set_index("row")[cols].add_prefix(f"{side}_")
        wide.append(part)
    return m.join(wide[0]).join(wide[1])


def missing_impact(m: pd.DataFrame, pm: pd.DataFrame, window: int = 10, regular: float = 0.5) -> pd.DataFrame:
    """Share of a club's regulars (>= `regular` of available minutes over its previous `window` matches)
    who did not start. Weighted by each regular's minutes share. NaN where player data is unavailable."""
    if pm.empty:
        return m.assign(home_missing=np.nan, away_missing=np.nan)
    order = m[["match_id", "date"]]
    pm = pm.merge(order, on="match_id")
    out: dict[tuple[str, str], float] = {}
    for club, grp in pm.groupby("club_id"):
        games = grp[["match_id", "date"]].drop_duplicates().sort_values("date").match_id.tolist()
        mins = (
            grp.pivot_table(index="match_id", columns="player_id", values="minutes", aggfunc="sum")
            .reindex(games)
            .fillna(0)
        )
        starts = (
            grp.pivot_table(index="match_id", columns="player_id", values="starts", aggfunc="sum")
            .reindex(games)
            .fillna(0)
        )
        share = mins.rolling(window, min_periods=3).sum().shift(1) / (
            90 * mins.rolling(window, min_periods=3).count().shift(1)
        )
        for mid in games:
            s = share.loc[mid]
            regs = s[s >= regular]
            if regs.empty:
                continue
            absent = regs[starts.loc[mid, regs.index] == 0]
            out[(mid, club)] = float(absent.sum() / regs.sum())
    m = m.copy()
    m["home_missing"] = [out.get((mid, h), np.nan) for mid, h in zip(m.match_id, m.home, strict=True)]
    m["away_missing"] = [out.get((mid, a), np.nan) for mid, a in zip(m.match_id, m.away, strict=True)]
    return m


def blocks(m: pd.DataFrame, size: int = 40) -> list[tuple[pd.Timestamp, pd.Index]]:
    """Chronological blocks of ~4 gameweeks: (first kick-off date, row index)."""
    out = []
    for _, season in m.groupby("season", sort=False):
        for i in range(0, len(season), size):
            part = season.iloc[i : i + size]
            out.append((part.date.min(), part.index))
    return out


XG_WEIGHT = 0.7  # share of xG in the blended Dixon–Coles target (chosen on validation seasons 2022-24)


def dixon_coles_walkforward(
    m: pd.DataFrame, start_season: str, years: float = 3.0, block: int = 40, xg_weight: float = XG_WEIGHT
) -> pd.DataFrame:
    """Out-of-sample Dixon–Coles probabilities for every match from `start_season` on, from two fits per block:
    `dc_*` on goals, and `dcx_*` on a goals/xG blend (goals alone where xG is unavailable, i.e. before 2022-23)."""
    m = m.copy()
    hx, ax = m.home_xg.notna(), m.away_xg.notna()
    m["home_t"] = np.where(hx, (1 - xg_weight) * m.home_goals + xg_weight * m.home_xg.fillna(0), m.home_goals)
    m["away_t"] = np.where(ax, (1 - xg_weight) * m.away_goals + xg_weight * m.away_xg.fillna(0), m.away_goals)
    cols = [f"{p}_{c}" for p in ("dc", "dcx") for c in ("ph", "pd", "pa", "lam", "mu")]
    values = np.full((len(m), len(cols)), np.nan)
    pos = {idx: i for i, idx in enumerate(m.index)}
    priors: dict[str, dict] = {}
    for t0, rows in blocks(m[m.season >= start_season], block):
        hist = m[(m.date < t0) & (m.date >= t0 - pd.Timedelta(days=int(365 * years)))]
        season = m.at[rows[0], "season"]
        if season not in priors:
            priors[season] = promoted_priors(m, season, hist, t0)
        fits = (
            fit_map(hist, t0, prior_mean=priors[season]["goals"]),
            fit_map(hist, t0, target=("home_t", "away_t"), prior_mean=priors[season]["blend"]),
        )
        for i in rows:
            home, away = m.at[i, "home"], m.at[i, "away"]
            row = []
            for params in fits:
                row += [*params.probs(home, away), *params.rates(home, away)]
            values[pos[i]] = row
    return m.drop(columns=["home_t", "away_t"]).assign(**dict(zip(cols, values.T, strict=True)))


def promoted_priors(m: pd.DataFrame, season: str, hist: pd.DataFrame, t0: pd.Timestamp) -> dict[str, dict]:
    """Prior centres for clubs promoted into `season`: the mean (att, def) of the clubs relegated from the
    previous season, fitted on everything before the season starts. Mirrors how Elo seats promoted clubs."""
    seasons = sorted(m.season.unique())
    i = seasons.index(season)
    if i == 0:
        return {"goals": {}, "blend": {}}
    now, before = set(m[m.season == season].home), set(m[m.season == seasons[i - 1]].home)
    promoted, relegated = now - before, before - now
    out = {}
    for key, target in (("goals", None), ("blend", ("home_t", "away_t"))):
        base = fit_map(hist, t0, target=target)
        rel = [p for t in relegated if (p := base.params_of(t))]
        seat = tuple(np.mean(rel, axis=0)) if rel else (0.0, 0.0)
        out[key] = {t: seat for t in promoted}
    return out


PRE_LINEUP = [
    "elo_home",
    "elo_away",
    "elo_diff",
    "dc_ph",
    "dc_pd",
    "dc_pa",
    "dc_lam",
    "dc_mu",
    "dcx_ph",
    "dcx_pd",
    "dcx_pa",
    "dcx_lam",
    "dcx_mu",
    *[f"{s}_{c}_l{n}" for s in ("home", "away") for c in ("gf", "ga", "pts", "xgf", "xga") for n in ROLL],
    "home_rest_days",
    "away_rest_days",
]
LINEUP = [*PRE_LINEUP, "home_missing", "away_missing"]
