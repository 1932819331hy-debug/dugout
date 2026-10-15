"""Read SPADL actions written by tools/spadl (socceraction runs there, isolated).

SPADL pitch: 105 x 68, every action oriented so the acting team attacks left -> right (x = 105 is the
opponent's goal line). Column names follow socceraction's `add_names` output.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
from dugout_pipeline.settings import REPO_ROOT

SPADL_DIR = REPO_ROOT / "data" / "raw" / "spadl"
LENGTH, WIDTH = 105.0, 68.0
MOVES = (
    "pass",
    "cross",
    "dribble",
    "take_on",
    "throw_in",
    "freekick_short",
    "freekick_crossed",
    "corner_short",
    "corner_crossed",
    "goalkick",
)
SHOTS = ("shot", "shot_freekick", "shot_penalty")


def load_actions(
    datasets: tuple[str, ...] = ("statsbomb", "wyscout_public"), root: Path = SPADL_DIR
) -> pd.DataFrame:
    parts = []
    for ds in datasets:
        files = str(root / ds / "actions" / "*.parquet").replace("\\", "/")
        if not list((root / ds / "actions").glob("*.parquet")):
            continue
        df = duckdb.sql(f"SELECT * FROM read_parquet('{files}', union_by_name = true)").df()
        df["dataset"] = ds
        parts.append(df)
    if not parts:
        raise FileNotFoundError(f"no SPADL actions under {root}; run `dugout load-open statsbomb|wyscout`")
    a = pd.concat(parts, ignore_index=True)
    a = a.sort_values(["dataset", "game_id", "period_id", "action_id"]).reset_index(drop=True)
    a["game_key"] = a["dataset"] + ":" + a["game_id"].astype(str)
    return a


def load_games(
    datasets: tuple[str, ...] = ("statsbomb", "wyscout_public"), root: Path = SPADL_DIR
) -> pd.DataFrame:
    out = []
    for ds in datasets:
        p = root / ds / "games.parquet"
        if p.exists():
            g = pd.read_parquet(p)
            g["dataset"] = ds
            g["game_key"] = ds + ":" + g["game_id"].astype(str)
            out.append(g)
    return pd.concat(out, ignore_index=True)


def load_players(
    datasets: tuple[str, ...] = ("statsbomb", "wyscout_public"), root: Path = SPADL_DIR
) -> pd.DataFrame:
    out = []
    for ds in datasets:
        p = root / ds / "players.parquet"
        if p.exists():
            out.append(pd.read_parquet(p).assign(dataset=ds))
    return pd.concat(out, ignore_index=True)


def is_goal(a: pd.DataFrame) -> pd.Series:
    return a.type_name.isin(SHOTS) & (a.result_name == "success")


def is_own_goal(a: pd.DataFrame) -> pd.Series:
    return a.result_name == "owngoal"
