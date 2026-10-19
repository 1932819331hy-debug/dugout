"""Transfer valuation: gradient-boosted regression of the fee's premium over market value, log(fee / market value),
on historical transfers (transfermarkt-datasets, CC0). Fair fee = today's market value x the predicted premium, so the
estimate moves with the market (a tree model of log(fee) on the transfer year cannot extrapolate past its last
training year, and underpriced Premier League deals by a third).
Features known at the time of each transfer:
  age; position; market value at the time ("quality" as the market saw it); minutes, goals and assists in the
  previous 365 days; league strength of the selling and buying clubs (median player value in that league
  that year); squad value of the selling and buying clubs; whether the buyer is a Premier League club and whether
  the move is between two Premier League clubs. Nationality was tested and adds nothing (valuation.md).
Contract months remaining is *not* available historically (the dataset only has current contract expiry), so it
cannot be learnt here; Transfer Realism uses it from current data with a documented prior weight instead.

Each estimate comes with a likely range (LEVEL = 80% of fees should land inside): split conformal by market-value
band, calibrated on the two years before the training cutoff (ValuationModel.calibrate).

Backtest: train on transfers before 2024-07-01, test from 2024-07-01; baseline = the market value. Fee ranges: method
chosen on validation (2023-07..2024-06), coverage on the test window and on summer-2026 Wikipedia fees.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import lightgbm as lgb
import numpy as np
import pandas as pd
from dugout_pipeline.settings import REPO_ROOT

TM_DIR = REPO_ROOT / "data" / "raw" / "transfermarkt"
SPLIT = pd.Timestamp("2024-07-01")
FEATURES = [
    "age",
    "log_mv",
    "minutes_365",
    "ga_p90_365",
    "apps_365",
    "log_from_league",
    "log_to_league",
    "same_league",
    "pos_Attack",
    "pos_Midfield",
    "pos_Defender",
    "pos_Goalkeeper",
    "to_pl",
    "pl_to_pl",
    "log_from_cv",
    "log_to_cv",
]
# the previous model (log fee on the transfer year), kept for the backtest comparison
FEATURES_V1 = [*FEATURES[:8], "year", *FEATURES[8:12]]
PL = "GB1"


def load(tm_dir: Path = TM_DIR) -> dict[str, pd.DataFrame]:
    return {
        n: pd.read_parquet(tm_dir / f"{n}.parquet")
        for n in ("players", "transfers", "player_valuations", "appearances", "clubs")
    }


def league_strength(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Median player market value per (domestic competition, year)."""
    v = t["player_valuations"].copy()
    v["year"] = pd.to_datetime(v["date"]).dt.year
    return (
        v.groupby(["player_club_domestic_competition_id", "year"])["market_value_in_eur"]
        .median()
        .rename("league_value")
        .reset_index()
        .rename(columns={"player_club_domestic_competition_id": "comp"})
    )


def build(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    tr = t["transfers"].copy()
    tr["date"] = pd.to_datetime(tr["transfer_date"])
    tr = tr[pd.to_numeric(tr["transfer_fee"], errors="coerce") > 0].copy()
    tr["fee"] = tr["transfer_fee"].astype(float)
    p = t["players"][["player_id", "date_of_birth", "position"]]
    tr = tr.merge(p, on="player_id", how="left")
    tr["age"] = (tr.date - pd.to_datetime(tr.date_of_birth)).dt.days / 365.25

    # market value at transfer: the transfer row's own value, else latest valuation before the date
    vals = t["player_valuations"][["player_id", "date", "market_value_in_eur"]].copy()
    vals["date"] = pd.to_datetime(vals["date"])
    tr = tr.sort_values("date")
    asof = pd.merge_asof(
        tr[["player_id", "date"]].reset_index(),
        vals.sort_values("date"),
        on="date",
        by="player_id",
        direction="backward",
    ).set_index("index")["market_value_in_eur"]
    tr["mv"] = pd.to_numeric(tr.get("market_value_in_eur"), errors="coerce").fillna(asof)
    tr["log_mv"] = np.log1p(tr.mv)

    # form in the previous 365 days
    ap = t["appearances"][["player_id", "date", "minutes_played", "goals", "assists"]].copy()
    ap["date"] = pd.to_datetime(ap["date"])
    form = _window_sums(tr[["player_id", "date"]], ap)
    tr = tr.join(form)
    tr["ga_p90_365"] = (tr.goals_365 + tr.assists_365) / tr.minutes_365.clip(lower=90) * 90

    clubs = t["clubs"][["club_id", "domestic_competition_id"]]
    ls = league_strength(t)
    tr["year"] = tr.date.dt.year
    for side in ("from", "to"):
        tr = tr.merge(
            clubs.rename(columns={"club_id": f"{side}_club_id", "domestic_competition_id": f"{side}_comp"}),
            on=f"{side}_club_id",
            how="left",
        )
        tr = tr.merge(
            ls.rename(columns={"comp": f"{side}_comp", "league_value": f"{side}_league"}),
            on=[f"{side}_comp", "year"],
            how="left",
        )
        tr[f"log_{side}_league"] = np.log1p(tr[f"{side}_league"])
    tr["same_league"] = (tr.from_comp == tr.to_comp).astype(float)
    tr["to_pl"] = (tr.to_comp == PL).astype(float)
    tr["pl_to_pl"] = ((tr.to_comp == PL) & (tr.from_comp == PL)).astype(float)
    cv = club_values(t)
    tr["season"] = tr.date.dt.year - (tr.date.dt.month < 6)
    for side in ("from", "to"):
        key = pd.MultiIndex.from_arrays([tr[f"{side}_club_id"].astype(str), tr.season])
        tr[f"log_{side}_cv"] = np.log1p(cv.reindex(key).fillna(0).to_numpy())
    for pos in ("Attack", "Midfield", "Defender", "Goalkeeper"):
        tr[f"pos_{pos}"] = (tr.position == pos).astype(float)
    tr["log_fee"] = np.log(tr.fee)
    return tr.dropna(subset=["age", "log_mv"]).reset_index(drop=True)


def club_values(t: dict[str, pd.DataFrame]) -> pd.Series:
    """Squad value by (club id, season starting that June): the sum of each player's latest valuation in the year
    before 1 June."""
    v = t["player_valuations"][["player_id", "date", "market_value_in_eur", "current_club_id"]].copy()
    v["date"] = pd.to_datetime(v.date)
    out = []
    for y in range(int(v.date.dt.year.min()) + 1, int(v.date.dt.year.max()) + 2):
        w = v[(v.date < f"{y}-06-01") & (v.date >= f"{y - 1}-06-01")].sort_values("date")
        s = w.groupby("player_id").tail(1).groupby("current_club_id").market_value_in_eur.sum()
        out.append(
            pd.Series(s.to_numpy(), index=pd.MultiIndex.from_arrays([s.index.astype(str), [y] * len(s)]))
        )
    return pd.concat(out)


def _window_sums(keys: pd.DataFrame, ap: pd.DataFrame, days: int = 365) -> pd.DataFrame:
    """Sum of minutes/goals/assists/appearances in (date - days, date) per key row, via cumulative sums."""
    ap = ap.sort_values(["player_id", "date"])
    out = pd.DataFrame(
        index=keys.index, columns=["minutes_365", "goals_365", "assists_365", "apps_365"], dtype=float
    )
    groups = dict(tuple(ap.groupby("player_id")))
    for pid, rows in keys.groupby("player_id"):
        g = groups.get(pid)
        if g is None:
            out.loc[rows.index] = 0.0
            continue
        d = g.date.to_numpy()
        cs = np.vstack(
            [
                np.zeros(4),
                np.cumsum(g[["minutes_played", "goals", "assists"]].assign(n=1).to_numpy(float), axis=0),
            ]
        )
        hi = np.searchsorted(d, rows.date.to_numpy(), side="left")
        lo = np.searchsorted(d, (rows.date - pd.Timedelta(days=days)).to_numpy(), side="left")
        out.loc[rows.index] = cs[hi] - cs[lo]
    return out


class ValuationModel:
    params: ClassVar[dict] = dict(
        n_estimators=600,
        learning_rate=0.03,
        num_leaves=31,
        min_child_samples=30,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        verbose=-1,
    )

    def fit(self, df: pd.DataFrame) -> ValuationModel:
        df = df[df.mv > 0]
        premium = df.log_fee - np.log(df.mv)
        self.model = lgb.LGBMRegressor(**self.params).fit(df[FEATURES], premium)
        return self

    offsets: ClassVar[dict[str, float]] = {}
    # the likely fee range: (lower, upper) log-error quantiles, pooled and per market-value band; set by calibrate
    pooled: tuple[float, float] | None = None
    bands: ClassVar[dict[int, tuple[float, float]]] = {}

    def calibrate(self, df: pd.DataFrame, cutoff: pd.Timestamp) -> ValuationModel:
        """Learned out of sample: a model fitted on transfers more than two years before `cutoff` is scored on the
        two years before it (the calibration window).
        - Per-buyer-league offsets (configured leagues): each league's median log error, shrunk towards zero by
          n / (n + 50), corrects its buyers' estimates (fees for Bundesliga buyers came in a fifth under the
          estimate: valuation.md).
        - Fee ranges (split conformal, by market-value band): the band's equal-tailed LEVEL interval of the
          calibration errors (after the offsets) around the estimate. Fees for cheap players scatter far more
          than for stars, so one pooled range was too narrow for them and too wide for the rest (valuation.md)."""
        cal, res = calibration_residuals(df, cutoff)
        self.offsets = league_offsets(cal, res)
        if len(res):
            res = res - cal.to_comp.map(self.offsets).fillna(0.0).to_numpy(float)
        self.pooled, self.bands = conformal_bands(cal.mv.to_numpy(float), res)
        return self

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """df needs FEATURES and `mv` (market value today, > 0); `to_comp` (buyer league) applies its offset.
        `low`/`high` (the likely range: LEVEL of fees land inside) are NaN until `calibrate`."""
        mu = np.log(df.mv.to_numpy(float)) + self.model.predict(df[FEATURES])
        if self.offsets and "to_comp" in df:
            mu = mu + df.to_comp.map(self.offsets).fillna(0.0).to_numpy(float)
        lo, hi = self.range(df.mv.to_numpy(float))
        return pd.DataFrame(
            {"fair_fee": np.exp(mu), "low": np.exp(mu + lo), "high": np.exp(mu + hi)},
            index=df.index,
        )

    def range(self, mv: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Log distance of the range's ends from the estimate, by each player's market-value band."""
        lo, hi = np.full(len(mv), np.nan), np.full(len(mv), np.nan)
        if self.pooled is None:
            return lo, hi
        band = value_band(mv)
        for b in range(len(BANDS) + 1):
            lo[band == b], hi[band == b] = self.bands.get(b, self.pooled)
        return lo, hi


OFFSET_YEARS, OFFSET_SHRINK, OFFSET_MIN_N = 2, 50, 20
# Fee ranges: LEVEL of fees should land inside. Market-value band edges (EUR) chosen on validation (transfers
# 2023-07..2024-06, valuation.md); a band with fewer than BAND_MIN_N calibration transfers uses the pooled range.
LEVEL = 0.8
BANDS = [2e6, 5e6, 15e6]
BAND_MIN_N = 100


def value_band(mv: np.ndarray) -> np.ndarray:
    """0 = under the first edge ... len(BANDS) = at or above the last."""
    return np.searchsorted(BANDS, np.asarray(mv, float), side="right")


def calibration_residuals(df: pd.DataFrame, cutoff: pd.Timestamp) -> tuple[pd.DataFrame, np.ndarray]:
    """The calibration window (the OFFSET_YEARS before `cutoff`) and its log errors (fee over estimate) from a
    model fitted on the transfers before the window, without league offsets."""
    start = cutoff - pd.DateOffset(years=OFFSET_YEARS)
    early, cal = df[df.date < start], df[(df.date >= start) & (df.date < cutoff) & (df.mv > 0)]
    if early.empty or cal.empty:
        return cal.iloc[:0], np.array([])
    pred = np.log(ValuationModel().fit(early).predict(cal).fair_fee.to_numpy())
    return cal, cal.log_fee.to_numpy() - pred


def league_offsets(cal: pd.DataFrame, res: np.ndarray) -> dict[str, float]:
    from dugout_pipeline.clubs import league_config, leagues

    comps = {league_config(lg)["provider_ids"].get("transfermarkt") for lg in leagues()} - {None}
    out = {}
    for c in sorted(comps):
        r = res[(cal.to_comp == c).to_numpy()]
        if len(r) >= OFFSET_MIN_N:
            out[c] = float(np.median(r) * len(r) / (len(r) + OFFSET_SHRINK))
    return out


def conformal_interval(res: np.ndarray, level: float = LEVEL) -> tuple[float, float]:
    """Split-conformal (lower, upper) bounds of signed errors with equal tails: the k-th smallest and k-th largest
    of n calibration errors, k = floor((n + 1)(1 - level) / 2), so a new exchangeable error falls inside with
    probability at least `level` (too few errors for that: unbounded)."""
    r = np.sort(np.asarray(res, float))
    k = int(np.floor((len(r) + 1) * (1 - level) / 2 + 1e-9))  # 0.1 * 100 is 9.99...
    if k < 1:
        return -np.inf, np.inf
    return float(r[k - 1]), float(r[-k])


def conformal_bands(
    mv: np.ndarray, res: np.ndarray, level: float = LEVEL, edges: list[float] | None = None
) -> tuple[tuple[float, float] | None, dict[int, tuple[float, float]]]:
    """Pooled interval, and one per market-value band with at least BAND_MIN_N calibration errors."""
    if len(res) < BAND_MIN_N:
        return None, {}
    band = np.searchsorted(edges, mv, side="right") if edges is not None else value_band(mv)
    per = {
        int(b): conformal_interval(res[band == b], level)
        for b in np.unique(band)
        if (band == b).sum() >= BAND_MIN_N
    }
    return conformal_interval(res, level), per


def _metrics(y_log: np.ndarray, pred_log: np.ndarray) -> dict:
    err = pred_log - y_log
    ape = np.abs(np.exp(pred_log) - np.exp(y_log)) / np.exp(y_log)
    return {
        "mae_log": float(np.mean(np.abs(err))),
        "median_ape": float(np.median(ape)),
        "within_25pct": float(np.mean(ape <= 0.25)),
        "n": len(y_log),
    }


def _coverage(y_log: np.ndarray, est: pd.DataFrame) -> dict:
    """How often the fee landed inside the likely range, which side it missed on, and how wide the range is."""
    y = np.exp(y_log)
    lo, hi, mid = (est[c].to_numpy(float) for c in ("low", "high", "fair_fee"))
    return {
        "n": len(y),
        "coverage": float(np.mean((y >= lo) & (y <= hi))) if len(y) else float("nan"),
        "below": float(np.mean(y < lo)) if len(y) else float("nan"),
        "above": float(np.mean(y > hi)) if len(y) else float("nan"),
        "median_width_eur": float(np.median(hi - lo)) if len(y) else float("nan"),
        "median_low_over_estimate": float(np.median(lo / mid)) if len(y) else float("nan"),
        "median_high_over_estimate": float(np.median(hi / mid)) if len(y) else float("nan"),
    }


# Range methods compared on validation (the shipped one is "value bands (4)", BANDS); every method's coverage is
# read on the same finer reporting grid
REPORT_BANDS = [1e6, 3e6, 10e6, 30e6]
REPORT_BAND_NAMES = ["under €1m", "€1m to €3m", "€3m to €10m", "€10m to €30m", "€30m or more"]
BAND_NAMES = ["under €2m", "€2m to €5m", "€5m to €15m", "€15m or more"]  # the shipped BANDS
RANGE_METHODS = {
    "training errors (previous range)": None,
    "pooled": [],
    "by buyer league": "league",
    "value bands (3)": [2e6, 10e6],
    "value bands (4)": BANDS,
    "value bands (5)": REPORT_BANDS,
}
VALIDATION = pd.Timestamp("2023-07-01")  # range method chosen on 2023-07..2024-06, before the test window


def _range_methods(df: pd.DataFrame, cutoff: pd.Timestamp, end: pd.Timestamp) -> dict[str, dict]:
    """Every candidate range for transfers in [cutoff, end), from a model fitted (and calibrated) before cutoff."""
    train, rows = df[df.date < cutoff], df[(df.date >= cutoff) & (df.date < end)]
    model = ValuationModel().fit(train).calibrate(df, cutoff)
    mu = np.log(model.predict(rows).fair_fee.to_numpy())
    y = rows.log_fee.to_numpy()
    cal, res = calibration_residuals(df, cutoff)
    res = res - cal.to_comp.map(model.offsets).fillna(0.0).to_numpy(float)
    out = {}
    for name, how in RANGE_METHODS.items():
        lo, hi = np.zeros(len(rows)), np.zeros(len(rows))
        if how is None:  # quantiles of the fitted model's own (in-sample) errors on its training rows
            t = train[train.mv > 0]
            lo[:], hi[:] = np.quantile(
                t.log_fee - np.log(t.mv) - model.model.predict(t[FEATURES]), [0.1, 0.9]
            )
        elif how == "league":
            pooled = conformal_interval(res)
            lo[:], hi[:] = pooled
            for c in rows.to_comp.dropna().unique():
                r = res[(cal.to_comp == c).to_numpy()]
                if len(r) >= BAND_MIN_N:
                    m = (rows.to_comp == c).to_numpy()
                    lo[m], hi[m] = conformal_interval(r)
        else:
            pooled, per = conformal_bands(cal.mv.to_numpy(float), res, edges=how)
            band = np.searchsorted(how, rows.mv.to_numpy(float), side="right")
            for b in np.unique(band):
                lo[band == b], hi[band == b] = per.get(int(b), pooled)
        est = pd.DataFrame({"fair_fee": np.exp(mu), "low": np.exp(mu + lo), "high": np.exp(mu + hi)})
        grid = np.searchsorted(REPORT_BANDS, rows.mv.to_numpy(float), side="right")
        per_band = [_coverage(y[grid == b], est[grid == b])["coverage"] for b in range(len(REPORT_BANDS) + 1)]
        out[name] = {
            **_coverage(y, est),
            "by_value_band": per_band,
            "worst_band_gap": float(np.nanmax(np.abs(np.array(per_band) - LEVEL))),
        }
    return out


HOLDOUT_FROM = pd.Timestamp("2026-06-01")  # summer 2026: Wikipedia fees the dataset does not have yet


def wiki_holdout(con, t: dict[str, pd.DataFrame], tm_transfers: pd.DataFrame) -> pd.DataFrame:
    """Summer-2026 fees from Wikipedia's transfer lists (`wiki_transfers`, Transfermarkt ids via Wikidata) that
    transfermarkt-datasets does not list (no transfer of the player within 60 days), as feature rows."""
    try:
        w = con.execute(
            """SELECT tm_player_id, date, tm_from_club, tm_to_club, fee_eur FROM wiki_transfers
               WHERE fee_eur > 0 AND tm_player_id IS NOT NULL AND kind = 'permanent' AND date >= ?""",
            [HOLDOUT_FROM.date()],
        ).fetchdf()
    except Exception:  # warehouse without the table
        return pd.DataFrame()
    if w.empty:
        return pd.DataFrame()
    w["player_id"] = pd.to_numeric(w.tm_player_id, errors="coerce")
    w["date"] = pd.to_datetime(w.date)
    w = w.dropna(subset=["player_id"]).astype({"player_id": "int64"})
    known = tm_transfers[["player_id", "transfer_date"]].assign(
        player_id=lambda d: pd.to_numeric(d.player_id, errors="coerce"),
        tm_date=lambda d: pd.to_datetime(d.transfer_date),
    )
    pair = w.reset_index().merge(known, on="player_id", how="left")
    seen = pair[(pair.tm_date - pair.date).abs() <= pd.Timedelta(days=60)]["index"].unique()
    w = w.drop(index=seen).drop_duplicates(["player_id", "date"])
    rows = pd.DataFrame(
        {
            "player_id": w.player_id.to_numpy(),
            "transfer_date": w.date.dt.strftime("%Y-%m-%d").to_numpy(),
            "from_club_id": pd.to_numeric(w.tm_from_club, errors="coerce").to_numpy(),
            "to_club_id": pd.to_numeric(w.tm_to_club, errors="coerce").to_numpy(),
            "transfer_fee": w.fee_eur.to_numpy(float),
            "market_value_in_eur": np.nan,  # build() takes the latest valuation before the date
        }
    )
    if rows.empty:
        return pd.DataFrame()
    return build({**t, "transfers": rows})


def backtest(out_dir: Path | None = None, con=None) -> dict:
    t = load()
    df = build(t)
    today = pd.Timestamp(datetime.now(UTC).date())  # some rows are pre-agreed future moves; exclude them
    df = df[df.mv > 0]
    train, test = df[df.date < SPLIT], df[(df.date >= SPLIT) & (df.date <= today)]
    model = ValuationModel().fit(train)
    pred_raw = np.log(model.predict(test).fair_fee.to_numpy())
    model.calibrate(df, SPLIT)  # offsets and ranges from transfers before the split only
    est = model.predict(test)
    pred = np.log(est.fair_fee.to_numpy())
    has_mv = test.mv.to_numpy() > 0
    prev = lgb.LGBMRegressor(**ValuationModel.params).fit(train[FEATURES_V1], train.log_fee)
    pred_prev = prev.predict(test[FEATURES_V1])
    y = test.log_fee.to_numpy()
    segments = {
        "all": np.ones(len(test), bool),
        "Premier League buyer": (test.to_pl == 1).to_numpy(),
        "Premier League to Premier League": (test.pl_to_pl == 1).to_numpy(),
        "Premier League buyer, age 24 or under": ((test.to_pl == 1) & (test.age <= 24)).to_numpy(),
    }
    # every other configured league as a buyer: the fair fee on those clubs' dossiers is "if sold within the league"
    from dugout_pipeline.clubs import league_config, leagues

    for lg in leagues():
        cfg = league_config(lg)
        comp = cfg["provider_ids"].get("transfermarkt")
        if comp and comp != PL:
            segments[f"{cfg['name']} buyer"] = (test.to_comp == comp).to_numpy()
            segments[f"{cfg['name']} to {cfg['name']}"] = (
                (test.to_comp == comp) & (test.from_comp == comp)
            ).to_numpy()
    seg = {
        name: {
            "n": int(m.sum()),
            "model": _metrics(y[m], pred[m]),
            "model_without_league_offsets": _metrics(y[m], pred_raw[m]),
            "previous_model": _metrics(y[m], pred_prev[m]),
            "market_value": _metrics(y[m], np.log(test.mv.to_numpy()[m])),
            "median_fee_over_estimate": float(np.exp(np.median(y[m] - pred[m]))),
            "median_fee_over_previous": float(np.exp(np.median(y[m] - pred_prev[m]))),
        }
        for name, m in segments.items()
    }
    band = np.searchsorted(REPORT_BANDS, test.mv.to_numpy(float), side="right")
    ranges = {
        "level": LEVEL,
        "calibration": {
            "from": str((SPLIT - pd.DateOffset(years=OFFSET_YEARS)).date()),
            "to": str(SPLIT.date()),
        },
        "bands": {
            BAND_NAMES[b]: [float(np.exp(v)) for v in model.bands.get(b, model.pooled)]
            for b in range(len(BANDS) + 1)
        },
        "segments": {name: _coverage(y[m], est[m]) for name, m in segments.items()},
        "by_value_band": {
            REPORT_BAND_NAMES[b]: _coverage(y[band == b], est[band == b])
            for b in range(len(REPORT_BANDS) + 1)
        },
        "validation": _range_methods(df, VALIDATION, SPLIT),
        "test_methods": _range_methods(df, SPLIT, today + pd.Timedelta(days=1)),
    }
    if con is not None:
        hold = wiki_holdout(con, t, t["transfers"])
        hold = hold[hold.mv > 0] if len(hold) else hold
        if len(hold):
            live = ValuationModel().fit(df[df.date < HOLDOUT_FROM]).calibrate(df, HOLDOUT_FROM)
            h_est = live.predict(hold)
            hy = hold.log_fee.to_numpy()
            hband = np.searchsorted(REPORT_BANDS, hold.mv.to_numpy(float), side="right")
            ranges["holdout_summer_2026"] = {
                "all": _coverage(hy, h_est),
                "Premier League buyer": _coverage(hy[hold.to_pl == 1], h_est[(hold.to_pl == 1).to_numpy()]),
                "other buyers": _coverage(hy[hold.to_pl != 1], h_est[(hold.to_pl != 1).to_numpy()]),
                "by_value_band": {
                    REPORT_BAND_NAMES[b]: _coverage(hy[hband == b], h_est[hband == b])
                    for b in range(len(REPORT_BANDS) + 1)
                },
                "model": _metrics(hy, np.log(h_est.fair_fee.to_numpy())),
                "market_value": _metrics(hy, np.log(hold.mv.to_numpy())),
            }
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "train": {"n": len(train), "from": str(train.date.min().date()), "to": str(train.date.max().date())},
        "test": {"from": str(test.date.min().date()), "to": str(test.date.max().date())},
        "model": _metrics(test.log_fee.to_numpy(), pred),
        "baseline_market_value": _metrics(
            test.log_fee.to_numpy()[has_mv], np.log(test.mv.to_numpy()[has_mv])
        ),
        "model_on_baseline_rows": _metrics(test.log_fee.to_numpy()[has_mv], pred[has_mv]),
        "segments": seg,
        "league_offsets": model.offsets,
        "ranges": ranges,
        "importance": dict(
            sorted(
                zip(FEATURES, model.model.feature_importances_.tolist(), strict=True), key=lambda kv: -kv[1]
            )
        ),
    }
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "valuation.json").write_text(json.dumps(report, indent=2))
        m, b = report["model_on_baseline_rows"], report["baseline_market_value"]
        lines = [
            "# Transfer valuation backtest",
            "",
            f"Generated {report['generated_at']}. Data: transfermarkt-datasets "
            "(CC0), transfers with a disclosed fee.",
            "",
            f"Train: {report['train']['n']} transfers {report['train']['from']} .. {report['train']['to']}. "
            f"Test: {report['test']['from']} .. {report['test']['to']}.",
            "",
            "| Estimate | MAE (log fee) | Median abs % error | Within ±25% | Transfers |",
            "|---|---|---|---|---|",
            f"| **dugout valuation** | {m['mae_log']:.3f} | {m['median_ape']:.1%} | {m['within_25pct']:.1%} | {m['n']} |",
            f"| Market value at the time | {b['mae_log']:.3f} | {b['median_ape']:.1%} | {b['within_25pct']:.1%} | {b['n']} |",
            "",
            "By segment (MAE of log fee; fee / estimate is the median ratio, 1.00 = unbiased):",
            "",
            "| Segment | Transfers | dugout | without league offsets | previous model | market value | fee / estimate (previous) |",
            "|---|---|---|---|---|---|---|",
            *[
                f"| {k} | {v['n']} | {v['model']['mae_log']:.3f} | {v['model_without_league_offsets']['mae_log']:.3f} | "
                f"{v['previous_model']['mae_log']:.3f} | "
                f"{v['market_value']['mae_log']:.3f} | {v['median_fee_over_estimate']:.2f} "
                f"({v['median_fee_over_previous']:.2f}) |"
                for k, v in report["segments"].items()
            ],
            "",
            "League offsets (log fee, buyers in each configured league; learned on 2022-07..2024-06 from a model "
            "fitted before 2022-07, shrunk by n / (n + 50); applied to every configured league, including the two "
            "where they made the test slightly worse): "
            + ", ".join(f"{c} {v:+.3f}" for c, v in report["league_offsets"].items()),
            "",
            "The previous model regressed log(fee) on the transfer year; trees cannot extrapolate a year they have not "
            "seen, so it underpriced recent Premier League deals. Nationality (an English or homegrown premium) was "
            "tested as a feature and added nothing once club context is known; it is not used.",
            "",
            "Feature importance (split count): "
            + ", ".join(f"{k} {v}" for k, v in report["importance"].items()),
            "",
            "Limitation: contract months remaining is not available historically, so it is not a feature.",
            "",
            "Other leagues' buyers (the fair fee on those clubs' dossiers): read MAE against the market-value column and "
            "the median ratio; a ratio below 1.00 means fees came in under the estimate (it runs high there).",
            "",
            *_range_lines(report["ranges"]),
        ]
        (out_dir / "valuation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def _cov_row(name: str, c: dict) -> str:
    if not c["n"]:
        return f"| {name} | 0 | – | – | – | – | – |"
    return (
        f"| {name} | {c['n']} | {c['coverage']:.1%} | {c['below']:.1%} | {c['above']:.1%} | "
        f"€{c['median_width_eur'] / 1e6:.1f}m | ×{c['median_low_over_estimate']:.2f} – "
        f"×{c['median_high_over_estimate']:.2f} |"
    )


def _range_lines(r: dict) -> list[str]:
    head = [
        "| Segment | Transfers | Inside the range | Below it | Above it | Median width | Range / estimate (median) |",
        "|---|---|---|---|---|---|---|",
    ]
    methods = [
        "| Method | Validation: inside | worst value band (gap) | median width | Test: inside | worst band gap |",
        "|---|---|---|---|---|---|",
        *[
            f"| {k}{' (shipped)' if k == 'value bands (4)' else ''} | {v['coverage']:.1%} | {v['worst_band_gap']:.3f} | "
            f"€{v['median_width_eur'] / 1e6:.1f}m | {r['test_methods'][k]['coverage']:.1%} | "
            f"{r['test_methods'][k]['worst_band_gap']:.3f} |"
            for k, v in r["validation"].items()
        ],
    ]
    out = [
        f"## Fee ranges ({r['level']:.0%})",
        "",
        "The site shows each fair fee with a likely range: split-conformal, calibrated on transfers "
        f"{r['calibration']['from']} .. {r['calibration']['to']} scored by a model fitted before them (the same "
        "window and model as the league offsets), so the range never sees the test window. The ends are the "
        "equal-tailed interval of those errors (after the offsets), separately for each market-value band: fees for "
        "cheap players scatter much more than for stars. Ranges as multiples of the estimate, by band: "
        + ", ".join(f"{k} ×{lo:.2f} – ×{hi:.2f}" for k, (lo, hi) in r["bands"].items())
        + ".",
        "",
        "Method chosen on validation (fitted and calibrated before 2023-07, scored on 2023-07..2024-06): the "
        "smallest worst gap between a value band's coverage and the target, then the narrower range. "
        "Training errors are the range used before (quantiles of the model's errors on its own training rows): too "
        "narrow out of sample, worst for cheap players.",
        "",
        *methods,
        "",
        "Test window, shipped range, by segment (below / above: fee under the low end / over the high end):",
        "",
        *head,
        *[_cov_row(k, v) for k, v in r["segments"].items()],
        "",
        "By market value at the time of the transfer:",
        "",
        *head,
        *[_cov_row(k, v) for k, v in r["by_value_band"].items()],
        "",
        _readout(r),
    ]
    h = r.get("holdout_summer_2026")
    if h:
        out += [
            "",
            "### Fresh holdout: summer 2026 (Wikipedia transfer lists)",
            "",
            "Fees from `wiki_transfers` (Wikipedia's transfer lists, Transfermarkt ids via Wikidata) dated from "
            f"{HOLDOUT_FROM.date()} for moves transfermarkt-datasets does not list, scored by a model fitted and "
            f"calibrated on transfers before {HOLDOUT_FROM.date()}. Mostly English pages (Premier League and "
            f"Championship buyers). MAE (log fee): dugout {h['model']['mae_log']:.3f}, market value "
            f"{h['market_value']['mae_log']:.3f} ({h['model']['n']} transfers).",
            "",
            *head,
            *[_cov_row(k, h[k]) for k in ("all", "Premier League buyer", "other buyers")],
            *[_cov_row(k, v) for k, v in h["by_value_band"].items()],
            "",
            f"With {h['all']['n']} transfers one standard error is about "
            f"{np.sqrt(LEVEL * (1 - LEVEL) / h['all']['n']):.1%}; the bands under €10m hold only a few dozen moves "
            "between them. Misses are mostly fees above the range.",
        ]
    return out


def _readout(r: dict) -> str:
    """Where the shipped range misses its target by more than five points on the test window (n >= 40)."""
    seg = {**r["segments"], **r["by_value_band"]}
    low = [
        f"{k} {v['coverage']:.0%}" for k, v in seg.items() if v["n"] >= 40 and v["coverage"] < LEVEL - 0.05
    ]
    high = [
        f"{k} {v['coverage']:.0%}" for k, v in seg.items() if v["n"] >= 40 and v["coverage"] > LEVEL + 0.05
    ]
    all_ = r["segments"]["all"]["coverage"]
    return (
        f"Reading: overall {all_:.1%} of test fees landed inside, a little over the target: the calibration errors "
        "come from a model fitted two years earlier on less data, so the range is slightly conservative. "
        f"Too narrow (under {LEVEL - 0.05:.0%}): {', '.join(low) or 'none'}. "
        f"Wider than needed (over {LEVEL + 0.05:.0%}): {', '.join(high) or 'none'}."
    )
