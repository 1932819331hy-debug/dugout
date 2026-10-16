"""Club Elo computed from results we hold (so we do not depend on ClubElo being up).

World-Football-Elo style: home advantage, goal-difference multiplier, K tuned on early seasons.
Promoted clubs enter at the mean rating of the clubs that were relegated the season before.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression


@dataclass
class Elo:
    k: float = 20.0
    home_adv: float = 60.0
    initial: float = 1500.0
    ratings: dict[str, float] = field(default_factory=dict)

    def expected(self, home: str, away: str) -> float:
        diff = self.ratings.get(home, self.initial) + self.home_adv - self.ratings.get(away, self.initial)
        return 1 / (1 + 10 ** (-diff / 400))

    def update(self, home: str, away: str, hg: int, ag: int) -> None:
        e = self.expected(home, away)
        s = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
        gd = abs(hg - ag)
        mult = 1.0 if gd <= 1 else 1.5 if gd == 2 else (11 + gd) / 8
        delta = self.k * mult * (s - e)
        self.ratings[home] = self.ratings.get(home, self.initial) + delta
        self.ratings[away] = self.ratings.get(away, self.initial) - delta


def pre_match_elo(matches: pd.DataFrame, k: float = 20.0, home_adv: float = 60.0) -> pd.DataFrame:
    """Adds elo_home / elo_away (ratings *before* each match). `matches` must be sorted by date."""
    out, _ = _run(matches, k, home_adv)
    return out


def elo_state(matches: pd.DataFrame, k: float = 20.0, home_adv: float = 60.0) -> Elo:
    """Ratings after every match in `matches` (for forecasting fixtures not yet played)."""
    return _run(matches, k, home_adv)[1]


def _run(matches: pd.DataFrame, k: float, home_adv: float) -> tuple[pd.DataFrame, Elo]:
    elo = Elo(k=k, home_adv=home_adv)
    out_h, out_a = np.empty(len(matches)), np.empty(len(matches))
    prev_teams: set[str] = set()
    season = None
    for i, r in enumerate(matches.itertuples()):
        if r.season != season:  # new season: seat promoted clubs at the relegated clubs' mean
            teams = set(matches.loc[matches.season == r.season, "home"])
            relegated = prev_teams - teams
            promoted = teams - prev_teams
            if prev_teams and relegated:
                seat = float(np.mean([elo.ratings.get(t, elo.initial) for t in relegated]))
                for t in promoted:
                    elo.ratings[t] = seat
            prev_teams, season = teams, r.season
        out_h[i] = elo.ratings.get(r.home, elo.initial)
        out_a[i] = elo.ratings.get(r.away, elo.initial)
        elo.update(r.home, r.away, int(r.home_goals), int(r.away_goals))
    return matches.assign(elo_home=out_h, elo_away=out_a, elo_diff=out_h + home_adv - out_a), elo


class EloOutcomeModel:
    """Elo baseline for 3-way probabilities: multinomial logistic regression on the Elo difference."""

    def fit(self, elo_diff: np.ndarray, outcomes: np.ndarray) -> EloOutcomeModel:
        self.clf = LogisticRegression(C=1e3, max_iter=1000).fit(
            np.asarray(elo_diff).reshape(-1, 1) / 100, outcomes
        )
        return self

    def predict(self, elo_diff: np.ndarray) -> np.ndarray:
        p = self.clf.predict_proba(np.asarray(elo_diff).reshape(-1, 1) / 100)
        order = [list(self.clf.classes_).index(c) for c in ("H", "D", "A")]
        return p[:, order]
