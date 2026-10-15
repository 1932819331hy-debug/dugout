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
import subprocess
from collections.abc import Iterable
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from dugout_pipeline.settings import REPO_ROOT, get_settings

log = logging.getLogger(__name__)

RAW = REPO_ROOT / "data" / "raw"
SPADL = RAW / "spadl"
TOOL = REPO_ROOT / "tools" / "spadl"

# Default open-data scope; extend freely. (competition_id, season_id) for StatsBomb.
STATSBOMB_DEFAULT = [(2, 27)]  # Premier League 2015/16 — the full season StatsBomb released openly
WYSCOUT_DEFAULT = ["England"]  # 2017/18 Premier League
METRICA_GAMES = ["1", "2"]  # Sample_Game_3 is EPTS (tracking-only)
SKILLCORNER_GAMES: list[str] = []


def run_spadl_tool(*args: str) -> None:
    """socceraction runs in its own pinned environment (tools/spadl); we only read the Parquet it writes."""
    cmd = [
        "uv",
        "run",
        "--project",
        str(TOOL),
        "python",
        str(TOOL / "convert.py"),
        *args,
        "--out",
        str(SPADL),
    ]
    log.info("running %s", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def store_events(con: duckdb.DuckDBPyConnection, dataset: str) -> int:
    """Load every converted game of a dataset into `events` (idempotent)."""
    files = (SPADL / dataset / "actions").glob("*.parquet")
    n = 0
    for f in files:
        has_xg = "xg" in pq.read_schema(f).names
        con.execute(
            f"""INSERT OR REPLACE INTO events BY NAME
                SELECT '{dataset}' AS dataset, CAST(game_id AS VARCHAR) AS game_id,
                       CAST(action_id AS VARCHAR) AS event_id, period_id AS period, time_seconds,
                       CAST(team_id AS VARCHAR) AS team_id, CAST(CAST(player_id AS BIGINT) AS VARCHAR) AS player_id,
                       type_name, result_name, bodypart_name AS bodypart, start_x, start_y, end_x, end_y,
                       {"xg" if has_xg else "NULL"} AS xg
                FROM read_parquet(?)""",
            [str(f)],
        )
        n += 1
    return n


def load_statsbomb(
    con, scope: Iterable[tuple[int, int]] = STATSBOMB_DEFAULT, limit: int | None = None
) -> dict:
    args = ["statsbomb", "--scope", ",".join(f"{c}:{s}" for c, s in scope)]
    run_spadl_tool(*args, *(["--limit", str(limit)] if limit is not None else []))
    return {"games_loaded": store_events(con, "statsbomb")}


def load_wyscout(con, countries: Iterable[str] = WYSCOUT_DEFAULT, limit: int | None = None) -> dict:
    cache = get_settings().cache_dir / "open" / "wyscout"
    args = ["wyscout", "--countries", ",".join(countries), "--cache", str(cache)]
    run_spadl_tool(*args, *(["--limit", str(limit)] if limit is not None else []))
    return {"games_loaded": store_events(con, "wyscout_public")}


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
