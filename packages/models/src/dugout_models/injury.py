"""Injury risk: discrete-time hazard of a new injury absence starting within the next 14 days.

At-risk rows: every Premier League match a player played (FPL history, 2022-23 on). An *injury episode* starts
at the first fixture a player misses with an injury reason (API-Football free-plan injury lists, 2022–2024);
suspensions, illness-free "coach's decision" and personal reasons are excluded.
Features use only information up to and including the match: age, recent load (minutes over the last 3
matches and 28 days, matches in the last 14 days), injury history (previous episodes, days since the last),
position. Logistic regression (calibrated, interpretable) vs gradient boosting; train 2022-24, test 2024-25.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from dugout_pipeline.ids import attach_catalogue
from dugout_pipeline.settings import REPO_ROOT
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

INJURY_DIR = REPO_ROOT / "data" / "raw" / "api_football"
TM_DIR = REPO_ROOT / "data" / "raw" / "transfermarkt"
HORIZON_DAYS = 14
NOT_INJURY = (
    "suspend",
    "red card",
    "yellow card",
    "coach",
    "personal",
    "international",
    "rest",
    "inactive",
    "loan",
    "transfer",
    "birth",
    "family",
    "lack of fitness",
    "ineligible",
)
FEATURES = [
    "age",
    "min_last3",
    "min_28d",
    "matches_14d",
    "prev_episodes",
    "days_since_episode",
    "is_gk",
    "is_def",
    "is_mid",
    "is_fwd",
    "season_week",
]


def injury_episodes() -> pd.DataFrame:
    df = pd.concat(
        [pd.read_parquet(p) for p in sorted(INJURY_DIR.glob("injuries_*.parquet"))], ignore_index=True
    )
    df = df[df.type == "Missing Fixture"].copy()
    reason = df.reason.fillna("").str.lower()
    df = df[~reason.str.contains("|".join(NOT_INJURY))].dropna(subset=["reep_id"])
    df["date"] = pd.to_datetime(df.date)
    df = df.sort_values(["reep_id", "date"])
    # a new episode when the gap to the previous missed fixture exceeds 10 days
    gap = df.groupby("reep_id").date.diff().dt.days
    starts = df[gap.isna() | (gap > 10)]
    return (
        starts[["reep_id", "date", "reason"]].rename(columns={"reep_id": "player_id"}).reset_index(drop=True)
    )


def panel(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    rows = con.execute(
        """SELECT s.player_id, CAST(m.kickoff_utc AS DATE) AS date, m.season, s.minutes
           FROM player_match_stats s JOIN matches m USING (match_id)
           WHERE s.source = 'fpl_history' AND s.minutes > 0 AND m.season IN ('2022-23', '2023-24', '2024-25')"""
    ).df()
    rows["date"] = pd.to_datetime(rows.date)
    rows = rows.sort_values(["player_id", "date"]).reset_index(drop=True)
    g = rows.groupby("player_id")
    rows["min_last3"] = g.minutes.transform(lambda s: s.rolling(3, min_periods=1).sum())
    rows["min_28d"] = _time_window_sum(rows, "minutes", 28)
    rows["matches_14d"] = _time_window_sum(rows.assign(one=1), "one", 14)
    rows["season_week"] = (rows.date - rows.groupby("season").date.transform("min")).dt.days // 7
    return rows


def _time_window_sum(rows: pd.DataFrame, col: str, days: int) -> np.ndarray:
    out = np.zeros(len(rows))
    for _, idx in rows.groupby("player_id").indices.items():
        d = rows.date.to_numpy()[idx]
        v = np.cumsum(np.concatenate([[0], rows[col].to_numpy()[idx]]))
        lo = np.searchsorted(d, d - np.timedelta64(days, "D"), side="right")
        out[idx] = v[np.arange(1, len(idx) + 1)] - v[lo]
    return out


def attach_player_facts(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> pd.DataFrame:
    """Birth date and position from transfermarkt-datasets via the Reep crosswalk."""
    tm = pd.read_parquet(TM_DIR / "players.parquet", columns=["player_id", "date_of_birth", "position"])
    tm["player_id"] = tm.player_id.astype(str)
    if not attach_catalogue(con):
        raise RuntimeError("Reep catalogue needed to join transfermarkt facts")
    bridge = con.execute("""SELECT reep_id, external_id AS tm_id FROM reep.bridges
                            WHERE provider='transfermarkt' AND namespace='spieler'""").df()
    facts = bridge.merge(tm, left_on="tm_id", right_on="player_id").drop(columns=["player_id"])
    df = df.merge(facts.drop_duplicates("reep_id"), left_on="player_id", right_on="reep_id", how="left")
    df["age"] = (df.date - pd.to_datetime(df.date_of_birth)).dt.days / 365.25
    for k, v in {
        "is_gk": "Goalkeeper",
        "is_def": "Defender",
        "is_mid": "Midfield",
        "is_fwd": "Attack",
    }.items():
        df[k] = (df.position == v).astype(float)
    return df


def build(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    p = panel(con)
    ep = injury_episodes()
    by_player = {k: v.date.to_numpy() for k, v in ep.groupby("player_id")}
    label = np.zeros(len(p), dtype=bool)
    prev = np.zeros(len(p))
    since = np.full(len(p), 999.0)
    for i, (pid, d) in enumerate(zip(p.player_id, p.date.to_numpy(), strict=True)):
        starts = by_player.get(pid)
        if starts is None:
            continue
        nxt = np.searchsorted(starts, d, side="right")
        label[i] = nxt < len(starts) and (starts[nxt] - d) <= np.timedelta64(HORIZON_DAYS, "D")
        prev[i] = nxt  # episodes that started on or before this match
        if nxt:
            since[i] = (d - starts[nxt - 1]) / np.timedelta64(1, "D")
    p["label"], p["prev_episodes"], p["days_since_episode"] = label, prev, np.minimum(since, 999)
    return attach_player_facts(con, p).dropna(subset=["age"])


def backtest(con: duckdb.DuckDBPyConnection, out_dir: Path | None = None) -> dict:
    df = build(con)
    train, test = df[df.season != "2024-25"], df[df.season == "2024-25"]
    base = np.full(len(test), train.label.mean())
    logit = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000)).fit(
        train[FEATURES], train.label
    )
    gbm = lgb.LGBMClassifier(
        n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=100, verbose=-1
    ).fit(train[FEATURES], train.label)
    res = {}
    for name, p in (
        ("logistic", logit.predict_proba(test[FEATURES])[:, 1]),
        ("gradient_boosting", gbm.predict_proba(test[FEATURES])[:, 1]),
        ("base_rate", base),
    ):
        res[name] = {
            "auc": float(roc_auc_score(test.label, p)) if name != "base_rate" else 0.5,
            "brier": float(brier_score_loss(test.label, p)),
        }
    coefs = dict(zip(FEATURES, logit[-1].coef_[0].round(3).tolist(), strict=True))
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "horizon_days": HORIZON_DAYS,
        "train_rows": len(train),
        "test_rows": len(test),
        "episodes": len(injury_episodes()),
        "positive_rate_test": float(test.label.mean()),
        "results": res,
        "logistic_coefficients": coefs,
    }
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "injury.json").write_text(json.dumps(report, indent=2))
        lines = [
            "# Injury risk backtest",
            "",
            f"Generated {report['generated_at']}. Label: a new injury absence starts "
            f"within {HORIZON_DAYS} days of a match played. Train 2022-23 + 2023-24, test 2024-25.",
            "",
            f"Injury episodes: {report['episodes']}. Test rows: {report['test_rows']} "
            f"(positive rate {report['positive_rate_test']:.2%}).",
            "",
            "| Model | AUC | Brier |",
            "|---|---|---|",
        ]
        lines += [f"| {k} | {v['auc']:.3f} | {v['brier']:.5f} |" for k, v in res.items()]
        lines += [
            "",
            "Logistic coefficients (standardised features): "
            + ", ".join(f"{k} {v}" for k, v in coefs.items()),
            "",
            "Data: API-Football free plan injury lists (2022–2024 seasons only); minutes from FPL; "
            "age/position from transfermarkt-datasets (CC0). Load counts Premier League minutes only.",
        ]
        (out_dir / "injury.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
