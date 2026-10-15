"""Player roles and similarity from per-90 profiles.

Profiles come from FPL/Opta per-match stats (the only free per-player data covering every current PL player):
xG, xA, goals, assists, threat, creativity, influence, saves and — from 2025-26 — tackles, recoveries and
clearances/blocks/interceptions. Within each position group:
  standardise -> Gaussian mixture (k chosen by BIC) -> roles named from their strongest features;
  UMAP gives 2-D coordinates for the website; cosine similarity finds like-for-like players.

Validation: a player's profile should be most similar to his own profile from the previous season
(self-retrieval hit rate), and roles should be stable under bootstrap resampling (adjusted Rand index).
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

MIN_MINUTES = 900
BASE = ["xg", "xa", "goals", "assists", "threat", "creativity", "influence"]
DEFENSIVE = ["tackles", "recoveries", "cbi"]
GK = ["saves", "xgc", "influence"]

# Role names by dominant feature, per position group.
ROLE_NAMES = {
    "DEF": {
        "creativity": "creative full-back",
        "xa": "creative full-back",
        "threat": "attacking full-back",
        "cbi": "stopper centre-back",
        "recoveries": "ball-winning defender",
        "tackles": "ball-winning defender",
        "influence": "ball-playing centre-back",
        "xg": "set-piece threat defender",
        "goals": "set-piece threat defender",
    },
    "MID": {
        "creativity": "creator",
        "xa": "creator",
        "threat": "attacking midfielder",
        "xg": "goalscoring midfielder",
        "goals": "goalscoring midfielder",
        "tackles": "ball-winning midfielder",
        "recoveries": "holding midfielder",
        "cbi": "holding midfielder",
        "influence": "deep-lying playmaker",
        "assists": "creator",
    },
    "FWD": {
        "xg": "penalty-box striker",
        "goals": "penalty-box striker",
        "threat": "penalty-box striker",
        "creativity": "creative forward",
        "xa": "creative forward",
        "assists": "creative forward",
        "influence": "complete forward",
        "recoveries": "pressing forward",
        "tackles": "pressing forward",
    },
}


def season_profiles(con: duckdb.DuckDBPyConnection, min_minutes: int = MIN_MINUTES) -> pd.DataFrame:
    """Per player-season per-90 profile. Position comes from the current FPL squad list."""
    df = con.execute(
        """
        SELECT s.player_id, m.season, any_value(p.name) AS name, any_value(p.position) AS position,
               arg_max(s.club_id, m.kickoff_utc) AS club_id, sum(s.minutes) AS minutes,
               sum(s.goals) AS goals, sum(s.assists) AS assists, sum(s.xg) AS xg, sum(s.xa) AS xa,
               sum(s.threat) AS threat, sum(s.creativity) AS creativity, sum(s.influence) AS influence,
               sum(s.saves) AS saves, sum(s.xgc) AS xgc,
               sum(s.tackles) AS tackles, sum(s.recoveries) AS recoveries, sum(s.cbi) AS cbi,
               count(s.tackles) AS def_matches, count(*) AS matches
        FROM player_match_stats s JOIN matches m USING (match_id) LEFT JOIN players p USING (player_id)
        WHERE s.source IN ('fpl_history', 'fpl')
        GROUP BY s.player_id, m.season HAVING sum(s.minutes) >= ?
        """,
        [min_minutes],
    ).df()
    for c in [*BASE, "saves", "xgc", *DEFENSIVE]:
        df[c] = df[c] / df.minutes * 90
    # defensive stats only where (almost) every match tracked them
    df.loc[df.def_matches < 0.9 * df.matches, DEFENSIVE] = np.nan
    return df


def feature_set(position: str, frame: pd.DataFrame) -> list[str]:
    if position == "GK":
        return GK
    return BASE + (DEFENSIVE if frame[DEFENSIVE].notna().all(axis=None) else [])


def fit_roles(profiles: pd.DataFrame, max_k: int = 4, seed: int = 7) -> pd.DataFrame:
    """Assigns `role` and 2-D `umap_x/umap_y` within each position group of one season's profiles."""
    import umap

    out = []
    for pos, grp in profiles.dropna(subset=["position"]).groupby("position"):
        cols = feature_set(pos, grp)
        grp = grp.dropna(subset=cols).copy()
        if len(grp) < 10:
            continue
        Z = StandardScaler().fit_transform(grp[cols])
        if pos == "GK":
            grp["role"], grp["cluster"] = "goalkeeper", 0
        else:
            best = min(
                (GaussianMixture(k, random_state=seed, n_init=3).fit(Z) for k in range(2, max_k + 1)),
                key=lambda g: g.bic(Z),
            )
            grp["cluster"] = best.predict(Z)
            names = {}
            for c in range(best.n_components):
                centre = pd.Series(Z[grp.cluster.to_numpy() == c].mean(axis=0), index=cols)
                names[c] = ROLE_NAMES.get(pos, {}).get(centre.idxmax(), f"{pos.lower()} profile {c + 1}")
            grp["role"] = grp.cluster.map(names)
        emb = umap.UMAP(n_neighbors=min(15, len(grp) - 1), random_state=seed).fit_transform(Z)
        grp["umap_x"], grp["umap_y"] = emb[:, 0], emb[:, 1]
        out.append(grp)
    return pd.concat(out, ignore_index=True)


def similarity(profiles: pd.DataFrame, cols: list[str]) -> tuple[np.ndarray, pd.DataFrame]:
    """Cosine similarity matrix over standardised profiles."""
    p = profiles.dropna(subset=cols).reset_index(drop=True)
    Z = StandardScaler().fit_transform(p[cols])
    Z /= np.linalg.norm(Z, axis=1, keepdims=True) + 1e-12
    return Z @ Z.T, p


def most_similar(profiles: pd.DataFrame, player_id: str, n: int = 5) -> pd.DataFrame:
    pos = profiles.loc[profiles.player_id == player_id, "position"].iloc[0]
    grp = profiles[profiles.position == pos]
    S, p = similarity(grp, feature_set(pos, grp))
    i = p.index[p.player_id == player_id][0]
    order = [j for j in np.argsort(-S[i]) if j != i][:n]
    return p.loc[order, ["player_id", "name", "club_id", "season"]].assign(similarity=S[i, order])


def self_retrieval(profiles: pd.DataFrame, season_a: str, season_b: str) -> dict:
    """For players with profiles in both seasons: is their own season-A profile the nearest neighbour
    (among all season-A profiles in the same position) of their season-B profile?"""
    hits1 = hits5 = n = 0
    for pos, grp in profiles.groupby("position"):
        a, b = grp[grp.season == season_a], grp[grp.season == season_b]
        cols = BASE if pos != "GK" else GK
        both = set(a.player_id) & set(b.player_id)
        if not both or len(a) < 6:
            continue
        sc = StandardScaler().fit(pd.concat([a, b])[cols])
        A = sc.transform(a[cols])
        A /= np.linalg.norm(A, axis=1, keepdims=True) + 1e-12
        ids = a.player_id.to_numpy()
        for pid in both:
            v = sc.transform(b.loc[b.player_id == pid, cols])[0]
            v /= np.linalg.norm(v) + 1e-12
            rank = list(ids[np.argsort(-(A @ v))]).index(pid)
            hits1 += rank == 0
            hits5 += rank < 5
            n += 1
    return {"players": n, "top1": hits1 / n if n else None, "top5": hits5 / n if n else None}


def role_stability(profiles: pd.DataFrame, n_boot: int = 20, seed: int = 7) -> float:
    """Mean adjusted Rand index between roles fitted on bootstrap resamples and on the full season."""
    rng = np.random.default_rng(seed)
    full = fit_roles(profiles).set_index("player_id").role
    scores = []
    for _ in range(n_boot):
        sample = profiles.sample(frac=1.0, replace=True, random_state=int(rng.integers(1e9))).drop_duplicates(
            "player_id"
        )
        boot = fit_roles(sample).set_index("player_id").role
        common = full.index.intersection(boot.index)
        scores.append(adjusted_rand_score(full[common], boot[common]))
    return float(np.mean(scores))
