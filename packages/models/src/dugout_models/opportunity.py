"""Playing-time outlook: expected minutes share for a player at a buying club.

Style similarity alone does not predict who plays (docs/backtests/fingerprint.md, embeddings.md). What does is
*opportunity*: the newcomer's standing relative to the incumbents at his position, his own recent minutes,
age and level. Trained on summer transfers (transfermarkt-datasets, CC0):

  prev_share       his minutes share last season          log_mv       market value at the transfer
  age, age2        age and curvature                      league_gap   buyer vs seller league strength
  rank_at_pos      his value rank among the club's incumbents at his position who stayed (1 = most valuable)
  value_vs_best    log(value / best incumbent value at the position)
  incumbents       number of 900+-minute incumbents at the position who stayed
  fee_vs_record    log(fee / buyer's largest fee in the previous 3 years)

Target: his minutes share at the new club that season. Time split: train 2016-2022, test 2023-2025.

Known leak (small): "incumbents who stayed" = incumbents who appeared for the club that season, so a January
departure or a season-long injury of an incumbent is visible to the model. For live use the incumbents are the
current squad, which is known.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score

from dugout_models.valuation import league_strength, load

FEATURES = [
    "prev_share",
    "log_mv",
    "age",
    "age2",
    "league_gap",
    "rank_at_pos",
    "value_vs_best",
    "incumbents",
    "fee_vs_record",
]
BASELINE = ["prev_share", "log_mv"]


def build() -> pd.DataFrame:
    t = load()
    players = t["players"].set_index("player_id")
    ap = t["appearances"][["player_id", "player_club_id", "date", "minutes_played"]].copy()
    ap["date"] = pd.to_datetime(ap.date)
    ap["season"] = np.where(ap.date.dt.month >= 7, ap.date.dt.year, ap.date.dt.year - 1)
    mins = (
        ap.groupby(["player_id", "player_club_id", "season"]).minutes_played.sum().rename("min").reset_index()
    )
    games = ap.groupby(["player_club_id", "season"]).date.nunique()
    vals = t["player_valuations"][["player_id", "date", "market_value_in_eur"]].copy()
    vals["date"] = pd.to_datetime(vals.date)
    clubs = t["clubs"].set_index("club_id").domestic_competition_id
    ls = league_strength(t).set_index(["comp", "year"]).league_value
    tr = t["transfers"].copy()
    tr["date"] = pd.to_datetime(tr.transfer_date)
    tr["fee"] = pd.to_numeric(tr.transfer_fee, errors="coerce")
    window = tr[tr.date.dt.month.isin([6, 7, 8]) & tr.date.dt.year.between(2016, 2025)]
    by_club_season = {k: g for k, g in mins.groupby(["player_club_id", "season"])}
    vals = vals.sort_values("date")
    value_asof = {
        y: vals[vals.date < f"{y}-06-01"].groupby("player_id").market_value_in_eur.last()
        for y in range(2016, 2026)
    }
    by_player_season = {k: g for k, g in mins.groupby(["player_id", "season"])}
    by_buyer = {k: g for k, g in tr[tr.fee.notna()].groupby("to_club_id")}
    rows = []
    for r in window.itertuples():
        y = r.date.year
        g_new = games.get((r.to_club_id, y))
        if not g_new or r.to_club_id not in clubs.index:
            continue
        pos = players.sub_position.get(r.player_id)
        prev_club = by_club_season.get((r.to_club_id, y - 1))
        if prev_club is None or pos is None:
            continue
        stayed = by_club_season.get((r.to_club_id, y))
        stayed_ids = set(stayed.player_id) if stayed is not None else set()
        inc = prev_club[
            (prev_club.player_id.map(players.sub_position) == pos)
            & (prev_club["min"] >= 900)
            & prev_club.player_id.isin(stayed_ids)
            & (prev_club.player_id != r.player_id)
        ]
        asof = value_asof[y]
        mv = pd.to_numeric(r.market_value_in_eur, errors="coerce")
        mv = mv if mv == mv and mv else asof.get(r.player_id, np.nan)
        inc_vals = inc.player_id.map(asof).dropna()
        own = by_player_season.get((r.player_id, y - 1), mins.iloc[:0])
        g_prev = games.get((own.player_club_id.iloc[0], y - 1)) if len(own) else None
        new = mins[
            (mins.player_id == r.player_id) & (mins.player_club_id == r.to_club_id) & (mins.season == y)
        ]
        hist = by_buyer.get(r.to_club_id, tr.iloc[:0])
        hist = hist[(hist.date < r.date) & (hist.date >= r.date - pd.Timedelta(days=1095))]
        record = hist.fee.max()
        sell_comp = clubs.get(r.from_club_id)
        dob = pd.to_datetime(players.date_of_birth.get(r.player_id))
        rows.append(
            {
                "season": y,
                "player_id": r.player_id,
                "to_club_id": r.to_club_id,
                "prev_share": own["min"].sum() / (90 * g_prev) if g_prev else np.nan,
                "log_mv": np.log1p(mv),
                "age": (r.date - dob).days / 365.25 if pd.notna(dob) else np.nan,
                "league_gap": np.log1p(ls.get((clubs[r.to_club_id], y), np.nan))
                - np.log1p(ls.get((sell_comp, y), np.nan)),
                "rank_at_pos": 1 + int((inc_vals > mv).sum()) if mv == mv else np.nan,
                "value_vs_best": np.log1p(mv) - np.log1p(inc_vals.max()) if len(inc_vals) else 0.0,
                "incumbents": len(inc),
                "fee_vs_record": np.log1p(r.fee or 0) - np.log1p(record or 0) if record == record else 0.0,
                "share": min(new["min"].sum() / (90 * g_new), 1.0),
            }
        )
    df = pd.DataFrame(rows)
    df["age2"] = (df.age - 26) ** 2
    return df.dropna(subset=["prev_share", "log_mv", "age"])


class OpportunityModel:
    params: ClassVar[dict] = dict(
        n_estimators=500,
        learning_rate=0.03,
        num_leaves=15,
        min_child_samples=50,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        verbose=-1,
    )

    def fit(self, df: pd.DataFrame) -> OpportunityModel:
        self.model = lgb.LGBMRegressor(**self.params).fit(df[FEATURES], df.share)
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return np.clip(self.model.predict(df[FEATURES]), 0, 1)


def backtest(out_dir: Path | None = None) -> dict:
    df = build()
    train, test = df[df.season <= 2022], df[df.season >= 2023]
    pred = OpportunityModel().fit(train).predict(test)
    base = np.clip(LinearRegression().fit(train[BASELINE], train.share).predict(test[BASELINE]), 0, 1)
    res = {}
    for name, p in (("opportunity_model", pred), ("baseline_prev_share_value", base)):
        res[name] = {
            "r2": float(r2_score(test.share, p)),
            "mae": float(mean_absolute_error(test.share, p)),
            "spearman": float(spearmanr(p, test.share)[0]),
        }
    # does the model separate starters from fringe players? share in top vs bottom predicted quartile
    q = pd.qcut(pred, 4, labels=False, duplicates="drop")
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "train": len(train),
        "test": len(test),
        "results": res,
        "actual_share_by_predicted_quartile": test.share.groupby(q).mean().round(3).tolist(),
    }
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "opportunity.json").write_text(json.dumps(report, indent=2))
        lines = [
            "# Playing-time outlook (the validated part of tactical fit)",
            "",
            f"Generated {report['generated_at']}. Summer transfers, transfermarkt-datasets (CC0). Train "
            f"2016-2022 ({report['train']}), test 2023-2025 ({report['test']}). Target: minutes share at the "
            "new club in the first season.",
            "",
            "| Model | R² | MAE | Spearman |",
            "|---|---|---|---|",
        ]
        for k, v in res.items():
            lines.append(f"| {k} | {v['r2']:.3f} | {v['mae']:.3f} | {v['spearman']:.3f} |")
        qs = report["actual_share_by_predicted_quartile"]
        lines += [
            "",
            "Actual minutes share by predicted quartile (lowest to highest): "
            + " / ".join(f"{x:.0%}" for x in qs),
            "",
            "In the dossier, *tactical fit* = this playing-time outlook (validated) shown next to *style "
            "similarity* to the manager's preferred profile (descriptive; it does not predict minutes).",
        ]
        (out_dir / "opportunity.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
