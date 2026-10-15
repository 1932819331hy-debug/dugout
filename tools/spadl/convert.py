"""Convert open event data to SPADL Parquet. Runs in its own environment (see pyproject.toml):

    uv run --project tools/spadl python tools/spadl/convert.py statsbomb --out data/raw/spadl --scope 2:27 --limit 5

Writes, under --out/<dataset>/:
  games.parquet              one row per game (ids, teams, competition, season, date)
  players.parquet            provider player ids and names (StatsBomb ids are bridged in the Reep Register)
  actions/<game_id>.parquet  SPADL actions with names + StatsBomb shot xG where available
Existing game files are skipped, so reruns only fetch new games.

Data credits: StatsBomb Open Data; Wyscout public dataset (Pappalardo et al., 2019, Scientific Data 6:236).
"""

from __future__ import annotations

import argparse
import time
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def _merge_meta(path: Path, df: pd.DataFrame, key: list[str]) -> None:
    if path.exists():
        df = pd.concat([pd.read_parquet(path), df]).drop_duplicates(subset=key, keep="last")
    _write(df, path)


def statsbomb(out: Path, scope: list[tuple[int, int]], limit: int | None, delay: float) -> dict:
    import socceraction.spadl as spadl
    from socceraction.data.statsbomb import StatsBombLoader
    from socceraction.spadl.statsbomb import convert_to_actions

    loader = StatsBombLoader(getter="remote", creds={"user": "", "passwd": ""})
    root, n = out / "statsbomb", 0
    for comp, season in scope:
        games = loader.games(comp, season)
        _merge_meta(root / "games.parquet", games.assign(dataset="statsbomb"), ["game_id"])
        for g in games.itertuples():
            if limit is not None and n >= limit:
                break
            path = root / "actions" / f"{g.game_id}.parquet"
            n += 1
            if path.exists():
                continue
            events = loader.events(g.game_id)
            actions = spadl.add_names(convert_to_actions(events, home_team_id=g.home_team_id))
            # keep StatsBomb's shot xG (joined back on the original event id)
            if "extra" in events:
                xg = events.set_index("event_id")["extra"].map(
                    lambda e: (e or {}).get("shot", {}).get("statsbomb_xg") if isinstance(e, dict) else None
                )
                actions["xg"] = actions["original_event_id"].map(xg)
            players = loader.players(g.game_id)
            _merge_meta(
                root / "players.parquet",
                players[["player_id", "player_name", "team_id"]].assign(dataset="statsbomb"),
                ["player_id"],
            )
            _write(actions, path)
            time.sleep(delay)  # polite to raw.githubusercontent.com
    return {"dataset": "statsbomb", "games": n}


def wyscout(out: Path, countries: list[str], limit: int | None, cache: Path) -> dict:
    import socceraction.spadl as spadl
    from socceraction.data.wyscout import PublicWyscoutLoader
    from socceraction.spadl.wyscout import convert_to_actions

    cache.mkdir(parents=True, exist_ok=True)
    loader = PublicWyscoutLoader(root=str(cache), download=not any(cache.iterdir()))
    comps = loader.competitions()
    root, n = out / "wyscout_public", 0
    for c in comps[comps["country_name"].isin(countries)].itertuples():
        games = loader.games(c.competition_id, c.season_id)
        _merge_meta(root / "games.parquet", games.assign(dataset="wyscout_public"), ["game_id"])
        for g in games.itertuples():
            if limit is not None and n >= limit:
                break
            path = root / "actions" / f"{g.game_id}.parquet"
            n += 1
            if path.exists():
                continue
            actions = spadl.add_names(
                convert_to_actions(loader.events(g.game_id), home_team_id=g.home_team_id)
            )
            players = loader.players(g.game_id)
            _merge_meta(
                root / "players.parquet",
                players[["player_id", "player_name", "team_id"]].assign(dataset="wyscout_public"),
                ["player_id"],
            )
            _write(actions, path)
    return {"dataset": "wyscout_public", "games": n}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("dataset", choices=["statsbomb", "wyscout"])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--limit", type=int)
    p.add_argument("--scope", default="2:27", help="StatsBomb competition:season pairs, comma-separated")
    p.add_argument("--countries", default="England", help="Wyscout countries, comma-separated")
    p.add_argument("--cache", type=Path, default=Path(".cache/open/wyscout"))
    p.add_argument("--delay", type=float, default=0.5)
    a = p.parse_args()
    if a.dataset == "statsbomb":
        scope = [tuple(int(x) for x in pair.split(":")) for pair in a.scope.split(",")]
        print(statsbomb(a.out, scope, a.limit, a.delay))
    else:
        print(wyscout(a.out, a.countries.split(","), a.limit, a.cache))


if __name__ == "__main__":
    main()
