"""Player potential: how good a player is likely to become, measured as projected market value in 2 and 4 years.

Market value is the only quality signal that exists for every professional player (transfermarkt-datasets, CC0).
It mixes ability with age, contract and hype, so the site shows it as a *level* ("the value of a typical Premier
League starter") next to the projection, never as a verdict on its own.

Snapshot on 1 June of year y (the same convention as transfer realism), for players valued in the 200 days before:
  age, age2, log_mv, mv_change_1y, mv_change_2y, peak_ratio, minutes_share (last 365 days), prev_share (the 365
  before), ga_p90, apps_365, log_league (median value in his league), top_tier, position, height
Target: log market value at y + h (latest valuation in the year before 1 June of y + h). LightGBM quantile
regression gives the 10th / 50th / 90th percentile (the 90th is shown as the "ceiling").

Players with no valuation at y + h (retired, dropped out of professional football, or simply not revalued) cannot be
scored and are left out of training, so projections lean optimistic for players at risk of dropping out. The
backtest reports how many such players there were.

Backtest (time split, nothing from after the snapshot is used at fit time):
  h = 2: train snapshots 2012-2021 (targets up to 2023), test 2023-2024 (targets 2025-2026)
  h = 4: train snapshots 2010-2019 (targets up to 2023), test 2021-2022 (targets 2025-2026)
Baselines: persistence (value stays the same) and an age curve (median change by age, fitted on train).
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

from dugout_models.valuation import league_strength, load

FEATURES = [
    "age",
    "age2",
    "log_mv",
    "mv_change_1y",
    "mv_change_2y",
    "peak_ratio",
    "minutes_share",
    "prev_share",
    "ga_p90",
    "apps_365",
    "log_league",
    "top_tier",
    "height",
    "pos_Attack",
    "pos_Midfield",
    "pos_Defender",
    "pos_Goalkeeper",
]
QUANTILES = (0.1, 0.5, 0.9)
HORIZONS = (2, 4)


def _latest_before(vals: pd.DataFrame, d: pd.Timestamp, window_days: int | None = None) -> pd.DataFrame:
    v = vals[vals.date < d]
    if window_days is not None:
        v = v[v.date >= d - pd.Timedelta(days=window_days)]
    return v.sort_values("date").groupby("player_id").tail(1).set_index("player_id")


def snapshot(t: dict[str, pd.DataFrame], d0: pd.Timestamp, top_tier: set[str]) -> pd.DataFrame:
    vals = t["player_valuations"]
    now = _latest_before(vals, d0, 200)
    out = pd.DataFrame(index=now.index)
    out["mv"] = now.market_value_in_eur.astype(float)
    out["comp"] = now.player_club_domestic_competition_id
    out["club_id"] = now.current_club_id.astype(str)
    for years, col in ((1, "mv_change_1y"), (2, "mv_change_2y")):
        past = _latest_before(vals, d0 - pd.Timedelta(days=365 * years)).market_value_in_eur
        out[col] = np.log1p(out.mv) - np.log1p(past.reindex(out.index).fillna(out.mv))
    peak = vals[vals.date < d0].groupby("player_id").market_value_in_eur.max()
    out["log_mv"] = np.log1p(out.mv)
    out["peak_ratio"] = out.log_mv - np.log1p(peak.reindex(out.index))
    players = t["players"].set_index("player_id")
    dob = pd.to_datetime(players.date_of_birth.reindex(out.index))
    out["age"] = (d0 - dob).dt.days / 365.25
    out["age2"] = (out.age - 24) ** 2
    out["height"] = players.height_in_cm.reindex(out.index)
    pos = players.position.reindex(out.index)
    for p in ("Attack", "Midfield", "Defender", "Goalkeeper"):
        out[f"pos_{p}"] = (pos == p).astype(float)
    ap = t["appearances"]
    for lo, hi, col in ((365, 0, "minutes_share"), (730, 365, "prev_share")):
        w = ap[(ap.date >= d0 - pd.Timedelta(days=lo)) & (ap.date < d0 - pd.Timedelta(days=hi))]
        mins = w.groupby("player_id").minutes_played.sum()
        games = w.groupby("player_club_id").date.nunique()
        main_club = w.groupby("player_id").player_club_id.agg(lambda s: s.mode().iloc[0])
        denom = 90 * main_club.map(games).clip(lower=10)
        out[col] = (mins / denom).reindex(out.index).fillna(0).clip(upper=1.2)
        if col == "minutes_share":
            ga = w.groupby("player_id")[["goals", "assists"]].sum().sum(axis=1)
            out["ga_p90"] = (ga / mins.clip(lower=90) * 90).reindex(out.index).fillna(0)
            out["apps_365"] = w.groupby("player_id").game_id.nunique().reindex(out.index).fillna(0)
    ls = league_strength(t).set_index(["comp", "year"]).league_value
    year = d0.year if (d0.month, d0.day) >= (6, 1) else d0.year - 1
    out["log_league"] = np.log1p([ls.get((c, year), ls.get((c, year - 1), np.nan)) for c in out.comp])
    out["top_tier"] = out.comp.isin(top_tier).astype(float)
    out["snapshot"] = d0
    return out.reset_index().rename(columns={"index": "player_id"})


def with_target(t: dict[str, pd.DataFrame], snap: pd.DataFrame, h: int) -> pd.DataFrame:
    d1 = snap.snapshot.iloc[0] + pd.DateOffset(years=h)
    fut = _latest_before(t["player_valuations"], d1, 365).market_value_in_eur
    snap = snap.copy()
    snap["target"] = np.log1p(snap.player_id.map(fut))
    return snap


class PotentialModel:
    params: ClassVar[dict] = dict(
        n_estimators=500,
        learning_rate=0.03,
        num_leaves=31,
        min_child_samples=100,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        verbose=-1,
    )

    def fit(self, df: pd.DataFrame) -> PotentialModel:
        # learn the *change* in log value; predicting levels lets the model coast on current value
        y = df.target - df.log_mv
        self.models = {
            q: lgb.LGBMRegressor(objective="quantile", alpha=q, **self.params).fit(df[FEATURES], y)
            for q in QUANTILES
        }
        return self

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        for q, m in self.models.items():
            out[f"q{int(q * 100)}"] = df.log_mv + m.predict(df[FEATURES])
        # quantile crossing can happen at the extremes; keep the band ordered
        out[["q10", "q50", "q90"]] = np.sort(out[["q10", "q50", "q90"]].to_numpy(), axis=1)
        return out


def frames(t: dict[str, pd.DataFrame], years: range, top_tier: set[str], h: int) -> pd.DataFrame:
    parts = [with_target(t, snapshot(t, pd.Timestamp(f"{y}-06-01"), top_tier), h) for y in years]
    return pd.concat(parts, ignore_index=True)


def _metrics(y: np.ndarray, pred: pd.DataFrame | np.ndarray) -> dict:
    p50 = pred["q50"].to_numpy() if isinstance(pred, pd.DataFrame) else pred
    ape = np.abs(np.expm1(p50) - np.expm1(y)) / np.expm1(y)
    out = {
        "mae_log": float(np.mean(np.abs(p50 - y))),
        "median_ape": float(np.median(ape)),
        "spearman": float(spearmanr(p50, y)[0]),
        "n": len(y),
    }
    if isinstance(pred, pd.DataFrame):
        out["coverage_10_90"] = float(np.mean((y >= pred.q10) & (y <= pred.q90)))
    return out


def prepare(t: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], set[str]]:
    from dugout_models.valuation import TM_DIR

    t = dict(t)
    v = t["player_valuations"].copy()
    v["date"] = pd.to_datetime(v.date)
    t["player_valuations"] = v
    ap = t["appearances"].copy()
    ap["date"] = pd.to_datetime(ap.date)
    t["appearances"] = ap
    comps = pd.read_parquet(TM_DIR / "competitions.parquet")
    return t, set(comps.loc[comps.sub_type == "first_tier", "competition_id"])


SPLITS = {2: (range(2012, 2022), range(2023, 2025)), 4: (range(2010, 2020), range(2021, 2023))}


def backtest(out_dir: Path | None = None) -> dict:
    t, top = prepare(load())
    report: dict = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "horizons": {}}
    for h, (train_years, test_years) in SPLITS.items():
        tr = frames(t, train_years, top, h)
        te = frames(t, test_years, top, h)
        dropped = float(te.target.isna().mean())
        tr, te = tr.dropna(subset=["target", "age"]), te.dropna(subset=["target", "age"])
        model = PotentialModel().fit(tr)
        pred = model.predict(te)
        bucket = (tr.age // 1).clip(16, 36)
        curve = (tr.target - tr.log_mv).groupby(bucket).median()
        age_curve = te.log_mv + (te.age // 1).clip(16, 36).map(curve).fillna(0)
        young = (te.age <= 21).to_numpy()
        y = te.target.to_numpy()
        report["horizons"][str(h)] = {
            "train_snapshots": [train_years.start, train_years.stop - 1],
            "test_snapshots": [test_years.start, test_years.stop - 1],
            "train_n": len(tr),
            "test_without_future_value": dropped,
            "model": _metrics(y, pred),
            "persistence": _metrics(y, te.log_mv.to_numpy()),
            "age_curve": _metrics(y, age_curve.to_numpy()),
            "model_age_21_or_under": _metrics(y[young], pred[young]),
            "age_curve_age_21_or_under": _metrics(y[young], age_curve.to_numpy()[young]),
            "importance": dict(
                sorted(
                    zip(FEATURES, model.models[0.5].feature_importances_.tolist(), strict=True),
                    key=lambda kv: -kv[1],
                )
            ),
        }
    if out_dir:
        write_report(report, out_dir)
    return report


def write_report(report: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "potential.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# Player potential backtest",
        "",
        f"Generated {report['generated_at']}. Target: log market value h years after a 1 June snapshot "
        "(transfermarkt-datasets, CC0). Time split: every training target is dated before the test snapshots.",
        "",
    ]
    for h, r in report["horizons"].items():
        lines += [
            f"## {h} years ahead",
            "",
            f"Train snapshots {r['train_snapshots'][0]}-{r['train_snapshots'][1]} ({r['train_n']} player-years); "
            f"test {r['test_snapshots'][0]}-{r['test_snapshots'][1]}. "
            f"{r['test_without_future_value']:.0%} of test players had no valuation {h} years on and are not scored.",
            "",
            "| Method | Players | MAE (log) | Median abs. % error | Spearman | 10-90% band coverage |",
            "|---|---|---|---|---|---|",
        ]
        for name, key in (
            ("**Potential model**", "model"),
            ("Age curve (median change by age)", "age_curve"),
            ("Persistence (value unchanged)", "persistence"),
            ("**Potential model**, age 21 or under", "model_age_21_or_under"),
            ("Age curve, age 21 or under", "age_curve_age_21_or_under"),
        ):
            m = r[key]
            cov = f"{m['coverage_10_90']:.0%}" if "coverage_10_90" in m else "—"
            lines.append(
                f"| {name} | {m['n']} | {m['mae_log']:.3f} | {m['median_ape']:.0%} | {m['spearman']:.3f} | {cov} |"
            )
        top = list(r["importance"])[:6]
        lines += ["", "Most used features: " + ", ".join(top), ""]
    lines += [
        "Market value mixes ability with age, contract and hype. The dossier shows the projection as a level "
        "(compared with current Premier League players) next to its 10-90% band, never alone.",
    ]
    (out_dir / "potential.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
