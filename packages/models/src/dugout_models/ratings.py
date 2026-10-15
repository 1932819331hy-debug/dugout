"""Player quality from open event data: VAEP and xT per 90.

VAEP probability models are fit on half of the games and evaluated on the other half (by game, so no
leakage within a match); then refit on all games to rate every action. Ratings are per 90 minutes over a
season, for players with at least MIN_MINUTES.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score

from dugout_models.spadl import SPADL_DIR, load_actions
from dugout_models.vaep import VAEP, features, labels
from dugout_models.xthreat import ExpectedThreat

MIN_MINUTES = 900


def player_minutes(datasets: tuple[str, ...], root: Path = SPADL_DIR) -> pd.DataFrame:
    parts = []
    for ds in datasets:
        p = root / ds / "player_games.parquet"
        if p.exists():
            parts.append(pd.read_parquet(p).assign(dataset=ds))
    pg = pd.concat(parts, ignore_index=True)
    pg["game_key"] = pg.dataset + ":" + pg.game_id.astype(str)
    return pg


def evaluate_vaep(actions: pd.DataFrame, X: pd.DataFrame, y: pd.DataFrame, seed: int = 7) -> dict:
    games = actions.game_key.unique()
    rng = np.random.default_rng(seed)
    test_games = set(rng.choice(games, size=len(games) // 2, replace=False))
    test = actions.game_key.isin(test_games).to_numpy()
    model = VAEP().fit(actions[~test], X[~test], y[~test])
    p = model.probabilities(actions[test], X[test])
    out = {}
    for k in ("scores", "concedes"):
        yt = y.loc[test, k].to_numpy()
        base = np.full(len(yt), y.loc[~test, k].mean())
        out[k] = {
            "auc": float(roc_auc_score(yt, p[k])),
            "brier": float(brier_score_loss(yt, p[k])),
            "brier_baseline": float(brier_score_loss(yt, base)),
            "positive_rate": float(yt.mean()),
        }
    out["train_games"], out["test_games"] = int(len(games) - len(test_games)), len(test_games)
    return out


def rate_players(datasets: tuple[str, ...] = ("statsbomb", "wyscout_public")) -> tuple[pd.DataFrame, dict]:
    actions = load_actions(datasets)
    X, y = features(actions), labels(actions)
    report = {"vaep_holdout": evaluate_vaep(actions, X, y)}
    vaep = VAEP().fit(actions, X, y)
    values = vaep.rate(actions, X)
    xt = ExpectedThreat().fit(actions)
    report["xt_grid_max"] = float(xt.xT.max())
    report["xt_iterations"] = xt.iterations
    a = pd.concat([actions[["dataset", "game_key", "player_id", "team_id"]], values], axis=1)
    a["xt_value"] = xt.rate(actions)
    agg = (
        a.groupby(["dataset", "player_id"])
        .agg(
            vaep=("vaep_value", "sum"),
            offensive=("offensive_value", "sum"),
            defensive=("defensive_value", "sum"),
            xt=("xt_value", "sum"),
            actions=("vaep_value", "size"),
        )
        .reset_index()
    )
    mins = (
        player_minutes(datasets)
        .groupby(["dataset", "player_id"])
        .agg(minutes=("minutes_played", "sum"), games=("game_id", "nunique"), name=("player_name", "last"))
        .reset_index()
    )
    r = agg.merge(mins, on=["dataset", "player_id"])
    r = r[r.minutes >= MIN_MINUTES].copy()
    for c in ("vaep", "offensive", "defensive", "xt"):
        r[f"{c}_p90"] = r[c] / r.minutes * 90
    return r.sort_values("vaep_p90", ascending=False).reset_index(drop=True), report


def write_report(ratings: pd.DataFrame, report: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **report,
        "players_rated": len(ratings),
        "min_minutes": MIN_MINUTES,
    }
    (out_dir / "player_ratings.json").write_text(json.dumps(report, indent=2))
    h = report["vaep_holdout"]
    lines = [
        "# Player quality: VAEP and xT",
        "",
        f"Generated {report['generated_at']}. Open event data: StatsBomb (PL 2015/16) and Wyscout public "
        "(PL 2017/18), converted to SPADL.",
        "",
        f"## VAEP probability models (held-out games: {h['test_games']}, trained on {h['train_games']})",
        "",
        "| Label | AUC | Brier | Brier (base rate) | Positive rate |",
        "|---|---|---|---|---|",
    ]
    for k in ("scores", "concedes"):
        v = h[k]
        lines.append(
            f"| {k} within 10 actions | {v['auc']:.3f} | {v['brier']:.4f} | {v['brier_baseline']:.4f} | "
            f"{v['positive_rate']:.4f} |"
        )
    lines += [
        "",
        f"xT: 16 x 12 grid, converged in {report['xt_iterations']} iterations; max cell value "
        f"{report['xt_grid_max']:.3f}.",
        "",
        f"## Top 15 players by VAEP per 90 (min {MIN_MINUTES} minutes)",
        "",
        "| Player | Dataset | Minutes | VAEP/90 | Offensive/90 | Defensive/90 | xT/90 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in ratings.head(15).itertuples():
        lines.append(
            f"| {r.name} | {r.dataset} | {int(r.minutes)} | {r.vaep_p90:.3f} | {r.offensive_p90:.3f} | "
            f"{r.defensive_p90:.3f} | {r.xt_p90:.3f} |"
        )
    (out_dir / "player_ratings.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
