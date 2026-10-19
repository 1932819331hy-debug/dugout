"""Where players actually start: transfermarkt-datasets `game_lineups` (CC0), starting XIs since 2023-24.

Transfermarkt's profile names one primary position, so versatile players were filed in one box: a midfielder who
often plays the holding role ("Central Midfield", e.g. Alex Scott, Lamine Camara) never reached a defensive-midfield
shortlist, and a centre-back who also plays right-back only fitted right-back "partly". The starting positions in
real lineups say where a player is actually used.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dugout_models.valuation import TM_DIR

POOL_SHARE = 0.25  # share of starts at a position to count him for that position on a shortlist
SLOT_SHARE, SLOT_STARTS = 0.10, 5  # to count a position as natural in the lineup model


def played(before: pd.Timestamp | None = None) -> pd.DataFrame:
    """One row per (Transfermarkt player id, position): starts there and share of his starts (before a date)."""
    path = TM_DIR / "game_lineups.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["player_id", "position", "starts", "share"])
    gl = pd.read_parquet(path, columns=["player_id", "position", "date"])
    if before is not None:
        gl = gl[pd.to_datetime(gl.date) < before]
    gl["player_id"] = gl.player_id.astype(str)
    out = gl.groupby(["player_id", "position"]).size().rename("starts").reset_index()
    out["share"] = out.starts / out.groupby("player_id").starts.transform("sum")
    return out


GROUP_STARTS = (
    10  # recorded starts before his lineups decide where he counts in a squad; below it, his listed one
)


def group_weights(
    p: pd.DataFrame,
    listed: pd.Series,
    group_of: dict[str, str],
    min_share: float = POOL_SHARE,
    min_starts: int = GROUP_STARTS,
) -> pd.DataFrame:
    """Where each player counts in his squad's depth: one row per (player_id, group) with a weight.

    `p` is `played()`, `listed` maps player id -> listed Transfermarkt sub-position, `group_of` maps a sub-position
    to its position group. His share of starts is summed per group (right-back + left-back = full-back), groups
    under `min_share` are dropped and the rest are weighted by share, renormalised so each player counts once: a
    centre-back with 60% of his starts there and 40% at right-back is 0.6 of a centre-back and 0.4 of a full-back.
    Players with fewer than `min_starts` recorded starts (new signings from leagues the dataset lacks, youngsters,
    long injuries) count fully at their listed position, as do players whose starts all fall under the threshold."""
    listed = listed.dropna()
    listed.index = listed.index.astype(str)
    p = p.assign(player_id=p.player_id.astype(str), group=p.position.map(group_of)).dropna(subset=["group"])
    p = p[p.player_id.isin(listed.index)]
    total = p.groupby("player_id").starts.sum()
    by = p.groupby(["player_id", "group"]).starts.sum().reset_index()
    by["share"] = by.starts / by.player_id.map(total)
    by = by[(by.player_id.map(total) >= min_starts) & (by.share >= min_share)]
    by["weight"] = by.share / by.groupby("player_id").share.transform("sum")
    rest = listed[~listed.index.isin(by.player_id)].map(group_of).dropna()
    fallback = pd.DataFrame(
        {"player_id": rest.index, "group": rest.to_numpy(), "share": np.nan, "weight": 1.0}
    )
    parts = [x for x in (by[["player_id", "group", "share", "weight"]], fallback) if len(x)]
    out = pd.concat(parts, ignore_index=True) if parts else fallback
    out["source"] = np.where(out.share.isna(), "listed", "played")
    return out.reset_index(drop=True)


def positions_played(
    min_share: float = POOL_SHARE, min_starts: int = 1, p: pd.DataFrame | None = None
) -> pd.Series:
    """Transfermarkt player id -> set of Transfermarkt position labels he starts at often enough."""
    p = played() if p is None else p
    p = p[(p.share >= min_share) & (p.starts >= min_starts)]
    return p.groupby("player_id").position.agg(set)
