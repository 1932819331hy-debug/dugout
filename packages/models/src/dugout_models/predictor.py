"""Match predictors.

- `StackedPredictor`: regularised multinomial logistic regression over a handful of strong, mostly
  out-of-sample signals (Elo difference, log-odds from the goals and xG Dixon–Coles models, xG form, rest,
  missing regulars). With ~3 000 training matches a linear stack is far more stable than trees on raw features.
- `BoostedStack`: XGBoost that starts from the stack's log-probabilities (`base_margin`) and only learns
  corrections from the raw features, so it cannot do worse than the stack by much.
- `TreePredictor`: plain XGBoost on all features (kept as a comparison).
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

LABELS = {"H": 0, "D": 1, "A": 2}
EPS = 1e-6


def _recency(df: pd.DataFrame, half_life_days: float) -> np.ndarray:
    age = (df.date.max() - df.date).dt.days.to_numpy()
    return 0.5 ** (age / half_life_days)


def stack_features(df: pd.DataFrame, lineup: bool) -> pd.DataFrame:
    def logit(prefix):
        ph, pd_, pa = (df[f"{prefix}_{k}"].clip(EPS, 1) for k in ("ph", "pd", "pa"))
        return np.log(ph / pa), np.log(pd_ / pa)

    f = pd.DataFrame(index=df.index)
    f["elo"] = df.elo_diff / 100
    f["dc_ha"], f["dc_da"] = logit("dc")
    f["dcx_ha"], f["dcx_da"] = logit("dcx")
    # xG form exists from 2022-23 only; elsewhere fall back to goal form so the coefficient is learnt on
    # one consistent signal instead of on zero-filled history.
    f["xgf"] = (df.home_xgf_l10.fillna(df.home_gf_l10) - df.away_xgf_l10.fillna(df.away_gf_l10)).fillna(0)
    f["xga"] = (df.home_xga_l10.fillna(df.home_ga_l10) - df.away_xga_l10.fillna(df.away_ga_l10)).fillna(0)
    f["pts"] = (df.home_pts_l5 - df.away_pts_l5).fillna(0)
    f["rest"] = (df.home_rest_days.fillna(14) - df.away_rest_days.fillna(14)) / 7
    if lineup:
        f["missing"] = df.home_missing.fillna(0) - df.away_missing.fillna(0)
    return f


# Chosen on validation seasons 2019-20..2023-24 (docs/backtests/predictor_validation.md): adding form, rest
# and xG-form terms made the stack worse at this sample size.
STACK_COLUMNS = ["elo", "dcx_ha", "dcx_da"]


class StackedPredictor:
    def __init__(
        self,
        lineup: bool = False,
        C: float = 0.5,
        half_life_days: float = 1100,
        columns: list[str] | None = None,
    ):
        self.lineup, self.C, self.half_life = lineup, C, half_life_days
        self.columns = (columns or STACK_COLUMNS) + (["missing"] if lineup else [])

    def _X(self, df: pd.DataFrame) -> pd.DataFrame:
        return stack_features(df, self.lineup)[self.columns]

    def fit(self, df: pd.DataFrame) -> StackedPredictor:
        X = self._X(df)
        self.scaler = StandardScaler().fit(X)
        self.clf = LogisticRegression(C=self.C, max_iter=2000)
        self.clf.fit(
            self.scaler.transform(X), df.result.map(LABELS), sample_weight=_recency(df, self.half_life)
        )
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self.clf.predict_proba(self.scaler.transform(self._X(df)))


class BoostedStack:
    PARAMS: ClassVar[dict] = dict(
        n_estimators=120,
        max_depth=2,
        learning_rate=0.02,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=20,
        reg_lambda=5.0,
        objective="multi:softprob",
        tree_method="hist",
        random_state=7,
    )

    def __init__(self, features: list[str], lineup: bool = False):
        self.features, self.stack = features, StackedPredictor(lineup=lineup)

    def fit(self, df: pd.DataFrame) -> BoostedStack:
        self.stack.fit(df)
        margin = np.log(self.stack.predict(df) + EPS)
        self.model = xgb.XGBClassifier(**self.PARAMS)
        self.model.fit(
            df[self.features],
            df.result.map(LABELS),
            base_margin=margin,
            sample_weight=_recency(df, self.stack.half_life),
        )
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        margin = np.log(self.stack.predict(df) + EPS)
        return self.model.predict_proba(df[self.features], base_margin=margin)


class TreePredictor:
    PARAMS: ClassVar[dict] = dict(
        n_estimators=300,
        max_depth=3,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        reg_lambda=2.0,
        objective="multi:softprob",
        tree_method="hist",
        random_state=7,
    )

    def __init__(self, features: list[str]):
        self.features = features

    def fit(self, df: pd.DataFrame) -> TreePredictor:
        self.model = xgb.XGBClassifier(**self.PARAMS)
        self.model.fit(df[self.features], df.result.map(LABELS), sample_weight=_recency(df, 730))
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(df[self.features])
