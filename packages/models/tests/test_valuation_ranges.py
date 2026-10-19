"""Fee ranges (split conformal by market-value band) on synthetic transfers: cheap players' fees scatter more."""

import numpy as np
import pandas as pd
from dugout_models import valuation as V


def _frame(n: int, seed: int, start: str, end: str) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    mv = np.exp(rng.uniform(np.log(2e5), np.log(8e7), n))
    df = pd.DataFrame({f: 0.0 for f in V.FEATURES}, index=range(n))
    df["log_mv"] = np.log1p(mv)
    df["age"] = rng.uniform(18, 32, n)
    df["mv"] = mv
    noise = np.where(mv < 2e6, 0.9, 0.25)  # log-fee spread: wide below €2m, narrow above
    df["log_fee"] = np.log(mv) + 0.1 + rng.normal(0, noise)
    span = (pd.Timestamp(end) - pd.Timestamp(start)).days
    df["date"] = pd.Timestamp(start) + pd.to_timedelta(rng.integers(0, span, n), unit="D")
    df["to_comp"] = "XX1"
    return df


def test_conformal_interval_finite_sample():
    r = np.arange(1, 100, dtype=float)  # n = 99: k = floor(100 * 0.1) = 10
    assert V.conformal_interval(r, 0.8) == (10.0, 90.0)
    assert V.conformal_interval(np.array([1.0, 2.0]), 0.8) == (-np.inf, np.inf)


def test_value_band_edges():
    assert V.value_band(np.array([5e5, 2e6, 4.9e6, 5e6, 1.5e7, 1e8])).tolist() == [0, 1, 1, 2, 3, 3]


def test_ranges_cover_and_follow_the_spread():
    hist = _frame(6000, 1, "2016-01-01", "2024-06-30")
    model = V.ValuationModel().fit(hist).calibrate(hist, pd.Timestamp("2024-07-01"))
    assert model.pooled is not None and set(model.bands) == {0, 1, 2, 3}
    width = {b: hi - lo for b, (lo, hi) in model.bands.items()}
    assert width[0] > 2 * width[3]  # cheap players get the wide range
    new = _frame(4000, 2, "2024-07-01", "2026-06-30")
    est = model.predict(new)
    assert (est.low < est.fair_fee).all() and (est.fair_fee < est.high).all()
    fee = np.exp(new.log_fee)
    inside = (fee >= est.low) & (fee <= est.high)
    assert abs(inside.mean() - V.LEVEL) < 0.04
    for b in (0, 3):
        m = V.value_band(new.mv.to_numpy()) == b
        assert abs(inside[m].mean() - V.LEVEL) < 0.07


def test_uncalibrated_model_has_no_range():
    hist = _frame(500, 3, "2016-01-01", "2024-06-30")
    est = V.ValuationModel().fit(hist).predict(hist.head(5))
    assert est.low.isna().all() and est.fair_fee.notna().all()
