"""Experiment: does FootballBERT similarity to the buying club's players at a position predict a newcomer's minutes?

    uv run python -m dugout_models.experiments.footballbert_fit [--no-guard]

Result (docs/backtests/embeddings.md): the naive signal is leakage (the model saw post-transfer lineups);
with the leakage guard (club profile built only from players the newcomer never played with there) it vanishes.
"""

from __future__ import annotations

import sys
import warnings

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import GroupKFold, cross_val_score

from dugout_models.embeddings import load_embeddings, norm_name
from dugout_models.valuation import load

CONTROLS = ["prev_share", "log_mv"]


def embedding_rows(players: pd.DataFrame, idx: pd.DataFrame) -> pd.Series:
    """transfermarkt player_id -> embedding row, for names unique on both sides."""
    counts = idx.key.value_counts()
    unique = idx[idx.key.map(counts) == 1].set_index("key").row
    p = players[["player_id", "name"]].copy()
    p["key"] = p.name.map(norm_name)
    p = p[p.key.map(p.key.value_counts()) == 1]
    p["row"] = p.key.map(unique)
    return p.dropna(subset=["row"]).set_index("player_id").row.astype(int)


def build(guard: bool = True) -> pd.DataFrame:
    t = load()
    w, idx = load_embeddings()
    unit = w / np.linalg.norm(w, axis=1, keepdims=True)
    rows_of = embedding_rows(t["players"], idx)
    subpos = t["players"].set_index("player_id").sub_position
    ap = t["appearances"][["player_id", "player_club_id", "date", "minutes_played"]].copy()
    ap["date"] = pd.to_datetime(ap.date)
    ap["season"] = np.where(ap.date.dt.month >= 7, ap.date.dt.year, ap.date.dt.year - 1)
    mins = (
        ap.groupby(["player_id", "player_club_id", "season"]).minutes_played.sum().rename("min").reset_index()
    )
    games = ap.groupby(["player_club_id", "season"]).date.nunique()
    tr = t["transfers"].copy()
    tr["date"] = pd.to_datetime(tr.transfer_date)
    tr = tr[tr.date.dt.month.isin([6, 7, 8]) & tr.date.dt.year.between(2016, 2025)]
    out = []
    for r in tr.itertuples():
        season = r.date.year
        if r.player_id not in rows_of.index:
            continue
        prev = mins[(mins.player_club_id == r.to_club_id) & (mins.season == season - 1)]
        prev = prev[
            (prev.player_id.map(subpos) == subpos.get(r.player_id))
            & prev.player_id.isin(rows_of.index)
            & (prev.player_id != r.player_id)
        ]
        if guard:
            stayed = mins[(mins.player_club_id == r.to_club_id) & (mins.season >= season) & (mins["min"] > 0)]
            prev = prev[~prev.player_id.isin(stayed.player_id)]
        g_new = games.get((r.to_club_id, season))
        if prev.empty or prev["min"].sum() < 450 or not g_new:
            continue
        centre = (unit[rows_of[prev.player_id].to_numpy()] * prev["min"].to_numpy()[:, None]).sum(0)
        fit = float(unit[rows_of[r.player_id]] @ (centre / np.linalg.norm(centre)))
        own = mins[(mins.player_id == r.player_id) & (mins.season == season - 1)]
        g_prev = games.get((own.player_club_id.iloc[0], season - 1)) if len(own) else None
        new = mins[
            (mins.player_id == r.player_id) & (mins.player_club_id == r.to_club_id) & (mins.season == season)
        ]
        out.append(
            {
                "season": season,
                "fit": fit,
                "prev_share": own["min"].sum() / (90 * g_prev) if g_prev else np.nan,
                "log_mv": np.log1p(pd.to_numeric(r.market_value_in_eur, errors="coerce") or 0),
                "share": min(new["min"].sum() / (90 * g_new), 1.0),
            }
        )
    return pd.DataFrame(out).dropna()


def evaluate(d: pd.DataFrame) -> dict:
    cv = GroupKFold(5)
    r2 = {}
    for name, cols in (("controls", CONTROLS), ("controls+fit", [*CONTROLS, "fit"])):
        r2[name] = float(
            cross_val_score(LinearRegression(), d[cols], d.share, cv=cv, groups=d.season, scoring="r2").mean()
        )
    rho, p = spearmanr(d.fit, d.share)
    return {"transfers": len(d), "spearman": float(rho), "p_value": float(p), "cv_r2": r2}


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    print(evaluate(build(guard="--no-guard" not in sys.argv)))
