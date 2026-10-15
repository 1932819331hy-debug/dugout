"""Scoring rules for 3-way (home / draw / away) probabilities. Lower is better for all three."""

from __future__ import annotations

import numpy as np

OUTCOMES = ("H", "D", "A")


def onehot(outcomes: np.ndarray) -> np.ndarray:
    idx = np.array([OUTCOMES.index(o) for o in outcomes])
    y = np.zeros((len(idx), 3))
    y[np.arange(len(idx)), idx] = 1
    return y


def rps(p: np.ndarray, y: np.ndarray) -> float:
    """Ranked probability score (ordered outcomes H < D < A), averaged over matches."""
    cp, cy = np.cumsum(p, axis=1)[:, :2], np.cumsum(y, axis=1)[:, :2]
    return float(np.mean(np.sum((cp - cy) ** 2, axis=1) / 2))


def log_loss(p: np.ndarray, y: np.ndarray, eps: float = 1e-12) -> float:
    return float(-np.mean(np.log(np.clip(np.sum(p * y, axis=1), eps, 1))))


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean(np.sum((p - y) ** 2, axis=1)))


def score(p: np.ndarray, outcomes: np.ndarray) -> dict[str, float]:
    y = onehot(outcomes)
    p = p / p.sum(axis=1, keepdims=True)
    return {"rps": rps(p, y), "log_loss": log_loss(p, y), "brier": brier(p, y), "n": len(outcomes)}


def implied_probs(odds_h, odds_d, odds_a) -> np.ndarray:
    """Bookmaker closing odds -> probabilities, removing the margin proportionally."""
    inv = 1 / np.column_stack([odds_h, odds_d, odds_a]).astype(float)
    return inv / inv.sum(axis=1, keepdims=True)


def outcome(home_goals, away_goals) -> np.ndarray:
    hg, ag = np.asarray(home_goals), np.asarray(away_goals)
    return np.where(hg > ag, "H", np.where(hg == ag, "D", "A"))
