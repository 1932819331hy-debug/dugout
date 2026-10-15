import numpy as np
import pandas as pd
import pytest
from dugout_models.dixon_coles import fit_map
from dugout_models.elo import Elo, EloOutcomeModel, pre_match_elo
from dugout_models.metrics import brier, implied_probs, log_loss, onehot, outcome, rps, score


def test_scoring_rules_known_values():
    y = onehot(np.array(["H", "A"]))
    perfect = y.copy()
    assert rps(perfect, y) == 0 and brier(perfect, y) == 0 and log_loss(perfect, y) < 1e-9
    uniform = np.full((2, 3), 1 / 3)
    # RPS of a uniform forecast when the home side wins: ((1/3-1)^2 + (2/3-1)^2) / 2
    assert rps(uniform[:1], y[:1]) == pytest.approx(((1 / 3 - 1) ** 2 + (2 / 3 - 1) ** 2) / 2)
    assert log_loss(uniform, y) == pytest.approx(np.log(3))


def test_rps_rewards_near_misses():
    y = onehot(np.array(["H"]))
    assert rps(np.array([[0.0, 1.0, 0.0]]), y) < rps(np.array([[0.0, 0.0, 1.0]]), y)


def test_implied_probs_remove_margin():
    p = implied_probs([2.0], [3.4], [3.8])
    assert p.sum() == pytest.approx(1) and p[0, 0] > p[0, 2]


def test_elo_is_zero_sum_and_home_advantage():
    e = Elo()
    e.update("a", "b", 2, 0)
    assert e.ratings["a"] + e.ratings["b"] == pytest.approx(3000)
    assert Elo().expected("x", "y") > 0.5


def _simulate(n_seasons=3, seed=1):
    rng = np.random.default_rng(seed)
    teams = [f"t{i}" for i in range(10)]
    att = dict(zip(teams, np.linspace(-0.4, 0.4, 10), strict=True))
    rows, day = [], pd.Timestamp("2020-08-01")
    for s in range(n_seasons):
        for h in teams:
            for a in teams:
                if h != a:
                    hg = rng.poisson(np.exp(0.3 + 0.25 + att[h] - att[a] * 0.5))
                    ag = rng.poisson(np.exp(0.3 + att[a] - att[h] * 0.5))
                    rows.append(
                        {
                            "season": f"{2020 + s}-{21 + s}",
                            "date": day,
                            "home": h,
                            "away": a,
                            "home_goals": hg,
                            "away_goals": ag,
                        }
                    )
                    day += pd.Timedelta(hours=12)
    df = pd.DataFrame(rows)
    df["result"] = outcome(df.home_goals, df.away_goals)
    return df, att


def test_dixon_coles_recovers_team_order_and_home_advantage():
    df, att = _simulate()
    p = fit_map(df, df.date.max() + pd.Timedelta(days=1))
    fitted = dict(zip(p.teams, p.att, strict=True))
    assert np.corrcoef([att[t] for t in p.teams], [fitted[t] for t in p.teams])[0, 1] > 0.9
    assert 0.1 < p.home < 0.45
    probs = p.probs("t9", "t0")
    assert probs.sum() == pytest.approx(1) and probs[0] > 0.6


def test_dixon_coles_accepts_xg_targets():
    df, _ = _simulate(1)
    df["home_t"], df["away_t"] = df.home_goals * 0.5 + 0.6, df.away_goals * 0.5 + 0.5
    p = fit_map(df, df.date.max(), target=("home_t", "away_t"))
    assert p.rho == 0.0 and p.probs("t0", "t1").sum() == pytest.approx(1)


def test_elo_baseline_beats_uniform_on_simulated_league():
    df, _ = _simulate(3)
    df = pre_match_elo(df)
    train, test = df.iloc[:180], df.iloc[180:]
    p = EloOutcomeModel().fit(train.elo_diff, train.result.to_numpy()).predict(test.elo_diff)
    assert score(p, test.result.to_numpy())["log_loss"] < np.log(3)
