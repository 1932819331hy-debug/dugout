"""VAEP: Valuing Actions by Estimating Probabilities (Decroos, Bransen, Van Haaren, Davis, KDD 2019).

For each action we estimate P(the acting team scores within the next 10 actions) and P(it concedes), from a
game state of the last 3 actions. An action's value is the change it causes:
    VAEP(a_i) = [P_score(i) - P_score(i-1)] - [P_concede(i) - P_concede(i-1)]
where the previous probabilities are swapped when possession changed between a_{i-1} and a_i.
Features and labels follow the paper / socceraction (MIT); this is our own implementation on SPADL Parquet.
"""

from __future__ import annotations

from typing import ClassVar

import lightgbm as lgb
import numpy as np
import pandas as pd

from dugout_models.spadl import LENGTH, WIDTH, is_goal, is_own_goal

NB_PREV = 3
HORIZON = 10
GOAL = np.array([LENGTH, WIDTH / 2])


def _state_features(a: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=a.index)
    for t in a.type_name.unique():
        f[f"type_{t}"] = (a.type_name == t).astype(np.int8)
    for r in ("success", "fail", "offside", "owngoal", "yellow_card", "red_card"):
        f[f"result_{r}"] = (a.result_name == r).astype(np.int8)
    for b in ("foot", "head", "other", "head/other", "foot_left", "foot_right"):
        f[f"body_{b}"] = (a.bodypart_name == b).astype(np.int8)
    f["start_x"], f["start_y"], f["end_x"], f["end_y"] = a.start_x, a.start_y, a.end_x, a.end_y
    f["dx"], f["dy"] = a.end_x - a.start_x, a.end_y - a.start_y
    f["movement"] = np.hypot(f.dx, f.dy)
    for p in ("start", "end"):
        dx, dy = GOAL[0] - a[f"{p}_x"], (GOAL[1] - a[f"{p}_y"]).abs()
        f[f"{p}_dist_goal"] = np.hypot(dx, dy)
        f[f"{p}_angle_goal"] = np.arctan2(dy, dx.clip(lower=1e-6))
    f["period"], f["time"] = a.period_id, a.time_seconds
    return f


def features(actions: pd.DataFrame) -> pd.DataFrame:
    """Game-state features: current action + the previous NB_PREV-1 actions (shifted within each game),
    expressed from the acting team's perspective, plus possession / tempo / score-state terms."""
    a = actions
    base = _state_features(a)
    game = a.game_key
    out = [base.add_suffix("_a0")]
    for k in range(1, NB_PREV):
        prev = base.groupby(game).shift(k)
        same_team = (a.team_id == a.team_id.groupby(game).shift(k)).astype(float)
        # mirror previous coordinates when the previous action was by the opponent
        for c in ("start_x", "end_x"):
            prev[c] = np.where(same_team == 1, prev[c], LENGTH - prev[c])
        for c in ("start_y", "end_y"):
            prev[c] = np.where(same_team == 1, prev[c], WIDTH - prev[c])
        prev[f"team_{k}"] = same_team
        prev["dt"] = a.time_seconds - a.time_seconds.groupby(game).shift(k)
        out.append(prev.add_suffix(f"_a{k}"))
    f = pd.concat(out, axis=1)
    f["goalscore_diff"] = score_diff(a)
    return f.fillna(0)


def score_diff(a: pd.DataFrame) -> np.ndarray:
    """Goal difference before each action, from the acting team's perspective (own goals credit the opponent)."""
    goal, own = is_goal(a).to_numpy(), is_own_goal(a).to_numpy()
    teams = a.team_id.to_numpy()
    diff = np.zeros(len(a))
    for idx in a.groupby("game_key").indices.values():
        both = set(teams[idx])
        tally = dict.fromkeys(both, 0)
        for i in idx:
            team = teams[i]
            diff[i] = 2 * tally[team] - sum(tally.values())
            if goal[i]:
                tally[team] += 1
            elif own[i]:
                for other in both - {team}:
                    tally[other] += 1
    return diff


def labels(actions: pd.DataFrame, horizon: int = HORIZON) -> pd.DataFrame:
    """scores: acting team scores within the next `horizon` actions (incl. this one); concedes: opponent does."""
    a = actions
    goal, own = is_goal(a).to_numpy(), is_own_goal(a).to_numpy()
    team = a.team_id.to_numpy()
    scores = np.zeros(len(a), dtype=bool)
    concedes = np.zeros(len(a), dtype=bool)
    for _, idx in a.groupby("game_key").indices.items():
        for j in range(len(idx)):
            i = idx[j]
            window = idx[j : j + horizon]
            for k in window:
                same = team[k] == team[i]
                if (goal[k] and same) or (own[k] and not same):
                    scores[i] = True
                if (goal[k] and not same) or (own[k] and same):
                    concedes[i] = True
    return pd.DataFrame({"scores": scores, "concedes": concedes}, index=a.index)


class VAEP:
    params: ClassVar[dict] = dict(
        n_estimators=300,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=50,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        verbose=-1,
    )

    def fit(
        self, actions: pd.DataFrame, X: pd.DataFrame | None = None, y: pd.DataFrame | None = None
    ) -> VAEP:
        X = features(actions) if X is None else X
        y = labels(actions) if y is None else y
        self.columns = list(X.columns)
        self.models = {k: lgb.LGBMClassifier(**self.params).fit(X, y[k]) for k in ("scores", "concedes")}
        return self

    def probabilities(self, actions: pd.DataFrame, X: pd.DataFrame | None = None) -> pd.DataFrame:
        X = (features(actions) if X is None else X).reindex(columns=self.columns, fill_value=0)
        return pd.DataFrame(
            {k: m.predict_proba(X)[:, 1] for k, m in self.models.items()}, index=actions.index
        )

    def rate(self, actions: pd.DataFrame, X: pd.DataFrame | None = None) -> pd.DataFrame:
        p = self.probabilities(actions, X)
        game = actions.game_key
        same = actions.team_id == actions.team_id.groupby(game).shift(1)
        prev_s = p.scores.groupby(game).shift(1)
        prev_c = p.concedes.groupby(game).shift(1)
        prev_scores = np.where(same, prev_s, prev_c)
        prev_concedes = np.where(same, prev_c, prev_s)
        first = prev_s.isna().to_numpy()
        prev_scores = np.where(first, 0, prev_scores)
        prev_concedes = np.where(first, 0, prev_concedes)
        # after a goal the next action (kick-off) starts from zero
        after_goal = (
            (is_goal(actions) | is_own_goal(actions)).groupby(game).shift(1, fill_value=False).to_numpy()
        )
        prev_scores = np.where(after_goal, 0, prev_scores)
        prev_concedes = np.where(after_goal, 0, prev_concedes)
        off = p.scores.to_numpy() - prev_scores
        dfn = -(p.concedes.to_numpy() - prev_concedes)
        return pd.DataFrame(
            {"offensive_value": off, "defensive_value": dfn, "vaep_value": off + dfn}, index=actions.index
        )
