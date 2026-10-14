"""Open datasets for training and backtests. Run on demand (`dugout load-open <dataset>`), never nightly.

Event data is converted to SPADL with socceraction and stored in `events`; tracking data is stored as one
Parquet per game under `data/raw/tracking/` (git-ignored: raw data is never redistributed).
Each game is cached as Parquet and skipped on later runs, so downloads happen once.

Credits (also in docs/sources.md and the README):
  StatsBomb Open Data; Wyscout public dataset (Pappalardo et al., 2019, Scientific Data 6:236);
  Metrica Sports sample data; SkillCorner Open Data; PFF FC World Cup 2022 data.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from pathlib import Path

import duckdb
import pandas as pd

from dugout_pipeline.settings import REPO_ROOT, get_settings

log = logging.getLogger(__name__)

RAW = REPO_ROOT / "data" / "raw"
EVENT_COLUMNS = [
    "dataset",
    "game_id",
    "event_id",
    "period",
    "time_seconds",
    "team_id",
    "player_id",
    "type_name",
    "result_name",
    "bodypart",
    "start_x",
    "start_y",
    "end_x",
    "end_y",
]

# Default open-data scope; extend freely. (competition_id, season_id) for StatsBomb.
STATSBOMB_DEFAULT = [(2, 27)]  # Premier League 2015/16 — the full season StatsBomb released openly
WYSCOUT_DEFAULT = ["England"]  # 2017/18 Premier League
METRICA_GAMES = ["1", "2"]  # Sample_Game_3 is EPTS (handled by kloppy too, but tracking-only)
SKILLCORNER_GAMES: list[str] = []  # filled from the SkillCorner open-data match list at runtime


def spadl_to_rows(actions: pd.DataFrame, dataset: str, game_id: str) -> pd.DataFrame:
    import socceraction.spadl as spadl

    a = spadl.add_names(actions)
    out = pd.DataFrame(
        {
            "dataset": dataset,
            "game_id": str(game_id),
            "event_id": a["action_id"].astype(str),
            "period": a["period_id"].astype(int),
            "time_seconds": a["time_seconds"].astype(float),
            "team_id": a["team_id"].astype(str),
            "player_id": a["player_id"].astype("Int64").astype(str),
            "type_name": a["type_name"],
            "result_name": a["result_name"],
            "bodypart": a["bodypart_name"],
            "start_x": a["start_x"],
            "start_y": a["start_y"],
            "end_x": a["end_x"],
            "end_y": a["end_y"],
        }
    )
    return out[EVENT_COLUMNS]


def store_events(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    con.register("_ev", df)
    try:
        con.execute("INSERT OR REPLACE INTO events BY NAME SELECT * FROM _ev")
    finally:
        con.unregister("_ev")
    return len(df)


def _cached(path: Path, build) -> pd.DataFrame:
    if path.exists():
        return pd.read_parquet(path)
    df = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


def load_statsbomb(
    con, scope: Iterable[tuple[int, int]] = STATSBOMB_DEFAULT, limit: int | None = None, delay: float = 0.5
) -> dict[str, int]:
    from socceraction.data.statsbomb import StatsBombLoader
    from socceraction.spadl.statsbomb import convert_to_actions

    loader, n_games, n_events = StatsBombLoader(getter="remote", creds={"user": "", "passwd": ""}), 0, 0
    for comp, season in scope:
        games = loader.games(comp, season)
        for g in games.itertuples():
            if limit is not None and n_games >= limit:
                break
            path = RAW / "events" / "statsbomb" / f"{g.game_id}.parquet"
            fresh = not path.exists()

            def build(g=g):
                ev = loader.events(g.game_id)
                return spadl_to_rows(
                    convert_to_actions(ev, home_team_id=g.home_team_id), "statsbomb", g.game_id
                )

            n_events += store_events(con, _cached(path, build))
            n_games += 1
            if fresh:
                time.sleep(delay)  # polite: raw.githubusercontent.com
    return {"games": n_games, "events": n_events}


def load_wyscout(con, countries: Iterable[str] = WYSCOUT_DEFAULT, limit: int | None = None) -> dict[str, int]:
    """Wyscout public dataset from figshare (downloaded once into .cache/open/wyscout by socceraction)."""
    from socceraction.data.wyscout import PublicWyscoutLoader
    from socceraction.spadl.wyscout import convert_to_actions

    root = get_settings().cache_dir / "open" / "wyscout"
    root.mkdir(parents=True, exist_ok=True)
    loader = PublicWyscoutLoader(root=str(root), download=not any(root.iterdir()))
    comps = loader.competitions()
    n_games = n_events = 0
    for c in comps[comps["country_name"].isin(list(countries))].itertuples():
        for g in loader.games(c.competition_id, c.season_id).itertuples():
            if limit is not None and n_games >= limit:
                break
            path = RAW / "events" / "wyscout_public" / f"{g.game_id}.parquet"

            def build(g=g):
                ev = loader.events(g.game_id)
                return spadl_to_rows(
                    convert_to_actions(ev, home_team_id=g.home_team_id), "wyscout_public", g.game_id
                )

            n_events += store_events(con, _cached(path, build))
            n_games += 1
    return {"games": n_games, "events": n_events}


def _tracking_to_parquet(dataset, out: Path) -> int:
    df = dataset.to_df(engine="pandas")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return len(df)


def load_metrica(con, games: Iterable[str] = METRICA_GAMES) -> dict[str, int]:
    from kloppy import metrica

    frames = 0
    for gid in games:
        out = RAW / "tracking" / "metrica" / f"{gid}.parquet"
        if not out.exists():
            frames += _tracking_to_parquet(metrica.load_open_data(match_id=gid, sample_rate=1 / 5), out)
    return {"games": len(list(games)), "frames_written": frames}


def load_skillcorner(con, games: Iterable[str] | None = None) -> dict[str, int]:
    from kloppy import skillcorner

    games = list(games or SKILLCORNER_GAMES or ["1925299"])  # kloppy's default open match if none listed
    frames = 0
    for gid in games:
        out = RAW / "tracking" / "skillcorner" / f"{gid}.parquet"
        if not out.exists():
            frames += _tracking_to_parquet(skillcorner.load_open_data(match_id=gid), out)
    return {"games": len(games), "frames_written": frames}


def load_pff(con, data_dir: Path | None = None, limit: int | None = None) -> dict[str, int]:
    """PFF FC World Cup 2022 requires a free sign-up; point PFF_DATA_DIR at the unzipped download."""
    from kloppy import pff

    data_dir = data_dir or get_settings().pff_data_dir
    if not data_dir or not Path(data_dir).exists():
        raise FileNotFoundError(
            "Set PFF_DATA_DIR to the PFF World Cup 2022 download (free sign-up at pff.com)."
        )
    data_dir = Path(data_dir)
    games = sorted(p.stem.split(".")[0] for p in (data_dir / "Tracking Data").glob("*.jsonl.bz2"))[:limit]
    frames = 0
    for gid in games:
        out = RAW / "tracking" / "pff_wc2022" / f"{gid}.parquet"
        if out.exists():
            continue
        ds = pff.load_tracking(
            meta_data=data_dir / "Metadata" / f"{gid}.json",
            roster_meta_data=data_dir / "Rosters" / f"{gid}.json",
            raw_data=data_dir / "Tracking Data" / f"{gid}.jsonl.bz2",
            sample_rate=1 / 5,
        )
        frames += _tracking_to_parquet(ds, out)
    return {"games": len(games), "frames_written": frames}


LOADERS = {
    "statsbomb": load_statsbomb,
    "wyscout": load_wyscout,
    "metrica": load_metrica,
    "skillcorner": load_skillcorner,
    "pff": load_pff,
}
