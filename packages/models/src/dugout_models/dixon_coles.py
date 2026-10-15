"""Dixon–Coles (1997) with time decay, as a Bayesian model.

  home goals ~ Poisson(exp(mu + home + att[h] - def[a])),  away goals ~ Poisson(exp(mu + att[a] - def[h]))
  with the low-score correction tau(x, y; rho) and match weights w = exp(-xi * days_ago).
  Priors: att, def ~ Normal(0, sigma) with sigma ~ HalfNormal(0.5); home ~ N(0.25, 0.2); rho ~ U(-0.2, 0.2).

`fit_bayes` samples the posterior with PyMC (NUTS): this is the reported Bayesian baseline.
`fit_map` finds the posterior mode of the *same* model with scipy (seconds instead of minutes); it is used for
walk-forward features over ten seasons, where hundreds of refits are needed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

MAX_GOALS = 10
XI = 0.0019  # per day: weight halves in ~1 year (Dixon & Coles report 0.0065/half-week)


@dataclass
class DCParams:
    teams: list[str]
    att: np.ndarray
    defn: np.ndarray
    home: float
    mu: float
    rho: float

    def rates(self, home: str, away: str) -> tuple[float, float]:
        idx = {t: i for i, t in enumerate(self.teams)}
        ah = self.att[idx[home]] if home in idx else 0.0
        dh = self.defn[idx[home]] if home in idx else 0.0
        aa = self.att[idx[away]] if away in idx else 0.0
        da = self.defn[idx[away]] if away in idx else 0.0
        return float(np.exp(self.mu + self.home + ah - da)), float(np.exp(self.mu + aa - dh))

    def params_of(self, team: str) -> tuple[float, float] | None:
        if team not in self.teams:
            return None
        i = self.teams.index(team)
        return float(self.att[i]), float(self.defn[i])

    def score_matrix(self, home: str, away: str) -> np.ndarray:
        lam, mu = self.rates(home, away)
        g = np.arange(MAX_GOALS + 1)
        m = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
        m[0, 0] *= 1 - lam * mu * self.rho
        m[0, 1] *= 1 + lam * self.rho
        m[1, 0] *= 1 + mu * self.rho
        m[1, 1] *= 1 - self.rho
        return m / m.sum()

    def probs(self, home: str, away: str) -> np.ndarray:
        m = self.score_matrix(home, away)
        return np.array([np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()])


def _prepare(df: pd.DataFrame, as_of: pd.Timestamp, xi: float):
    teams = sorted(set(df.home) | set(df.away))
    idx = {t: i for i, t in enumerate(teams)}
    h = df.home.map(idx).to_numpy()
    a = df.away.map(idx).to_numpy()
    w = np.exp(-xi * (as_of - df.date).dt.days.to_numpy())
    return teams, h, a, df.home_goals.to_numpy(), df.away_goals.to_numpy(), w


def _log_tau(x, y, lam, mu, rho):
    tau = np.ones_like(lam)
    tau = np.where((x == 0) & (y == 0), 1 - lam * mu * rho, tau)
    tau = np.where((x == 0) & (y == 1), 1 + lam * rho, tau)
    tau = np.where((x == 1) & (y == 0), 1 + mu * rho, tau)
    tau = np.where((x == 1) & (y == 1), 1 - rho, tau)
    return np.log(np.clip(tau, 1e-10, None))


def fit_map(
    df: pd.DataFrame,
    as_of: pd.Timestamp,
    xi: float = XI,
    sigma: float = 0.35,
    target: tuple[str, str] | None = None,
    prior_mean: dict[str, tuple[float, float]] | None = None,
) -> DCParams:
    """Posterior mode (MAP) of the Bayesian model, with sigma fixed at a typical posterior value.

    `target` swaps goals for other (possibly non-integer) per-side columns, e.g. a goals/xG blend. The Poisson
    kernel x*log(lam) - lam is then a quasi-likelihood and the low-score correction is switched off (rho = 0).
    """
    teams, h, a, x, y, w = _prepare(df, as_of, xi)
    if target:
        x, y = df[target[0]].to_numpy(dtype=float), df[target[1]].to_numpy(dtype=float)
    n = len(teams)
    # prior centres (att, def) per team; promoted clubs start near the clubs they replaced, not at the mean
    pa = np.array([(prior_mean or {}).get(t, (0.0, 0.0))[0] for t in teams])
    pdf = np.array([(prior_mean or {}).get(t, (0.0, 0.0))[1] for t in teams])

    def nlp(theta):
        att, dfn = theta[:n], theta[n : 2 * n]
        home, mu, rho = theta[2 * n], theta[2 * n + 1], theta[2 * n + 2]
        lam = np.exp(mu + home + att[h] - dfn[a])
        mmu = np.exp(mu + att[a] - dfn[h])
        ll = (x * np.log(lam) - lam) + (y * np.log(mmu) - mmu)
        if not target:
            ll = ll + _log_tau(x, y, lam, mmu, rho)
        prior = (
            -0.5 * (np.sum((att - pa) ** 2) + np.sum((dfn - pdf) ** 2)) / sigma**2
            - 0.5 * ((home - 0.25) / 0.2) ** 2
        )
        return -(np.sum(w * ll) + prior)

    theta0 = np.concatenate([pa, pdf, [0.25, 0.3, 0.0]])
    bounds = [(None, None)] * (2 * n + 2) + [(0.0, 0.0) if target else (-0.2, 0.2)]
    res = minimize(nlp, theta0, method="L-BFGS-B", bounds=bounds)
    t = res.x
    return DCParams(teams, t[:n], t[n : 2 * n], float(t[2 * n]), float(t[2 * n + 1]), float(t[2 * n + 2]))


def fit_bayes(
    df: pd.DataFrame,
    as_of: pd.Timestamp,
    xi: float = XI,
    draws: int = 500,
    tune: int = 500,
    chains: int = 2,
    seed: int = 7,
    prior_mean: dict[str, tuple[float, float]] | None = None,
) -> tuple[DCParams, object]:
    """Full posterior with PyMC NUTS. Returns posterior-mean parameters (for prediction) and the trace."""
    import pymc as pm
    import pytensor.tensor as pt

    teams, h, a, x, y, w = _prepare(df, as_of, xi)
    n = len(teams)
    pa = np.array([(prior_mean or {}).get(t, (0.0, 0.0))[0] for t in teams])
    pdf = np.array([(prior_mean or {}).get(t, (0.0, 0.0))[1] for t in teams])
    with pm.Model():
        sigma = pm.HalfNormal("sigma", 0.5)
        att_raw = pm.Normal("att_raw", 0, 1, shape=n)
        def_raw = pm.Normal("def_raw", 0, 1, shape=n)
        att = pm.Deterministic("att", pa + sigma * (att_raw - att_raw.mean()))
        dfn = pm.Deterministic("def", pdf + sigma * (def_raw - def_raw.mean()))
        home = pm.Normal("home", 0.25, 0.2)
        mu = pm.Normal("mu", 0.3, 0.5)
        rho = pm.Uniform("rho", -0.2, 0.2)
        lam = pt.exp(mu + home + att[h] - dfn[a])
        mmu = pt.exp(mu + att[a] - dfn[h])
        tau = pt.switch(
            pt.and_(pt.eq(x, 0), pt.eq(y, 0)),
            1 - lam * mmu * rho,
            pt.switch(
                pt.and_(pt.eq(x, 0), pt.eq(y, 1)),
                1 + lam * rho,
                pt.switch(
                    pt.and_(pt.eq(x, 1), pt.eq(y, 0)),
                    1 + mmu * rho,
                    pt.switch(pt.and_(pt.eq(x, 1), pt.eq(y, 1)), 1 - rho, 1.0),
                ),
            ),
        )
        ll = (
            pm.logp(pm.Poisson.dist(lam), x)
            + pm.logp(pm.Poisson.dist(mmu), y)
            + pt.log(pt.clip(tau, 1e-10, np.inf))
        )
        pm.Potential("weighted_ll", pt.sum(w * ll))
        trace = pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            random_seed=seed,
            progressbar=False,
            compute_convergence_checks=False,
        )
    post = trace.posterior
    mean = lambda v: post[v].mean(("chain", "draw")).values  # noqa: E731
    return DCParams(
        teams, mean("att"), mean("def"), float(mean("home")), float(mean("mu")), float(mean("rho"))
    ), trace
