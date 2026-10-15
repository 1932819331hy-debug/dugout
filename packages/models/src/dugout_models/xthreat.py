"""Expected Threat (Karun Singh, 2019) on SPADL actions.

xT(cell) = P(shot | cell) * P(goal | shot, cell) + P(move | cell) * sum_z T(cell -> z) * xT(z), solved by iteration.
Move transitions use successful moves only, normalised over all move attempts from the cell (failed moves lose
the ball, i.e. contribute 0). An action's value is xT(end) - xT(start) for successful moves.

Ported from the algorithm as described by Singh and implemented in socceraction (MIT); our own code.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from dugout_models.spadl import LENGTH, MOVES, SHOTS, WIDTH


@dataclass
class ExpectedThreat:
    l: int = 16  # cells along the pitch  # noqa: E741
    w: int = 12  # cells across the pitch
    eps: float = 1e-5
    max_iter: int = 200

    def _cell(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        xi = np.clip((x / LENGTH * self.l).astype(int), 0, self.l - 1)
        yj = np.clip((y / WIDTH * self.w).astype(int), 0, self.w - 1)
        return yj * self.l + xi

    def fit(self, actions: pd.DataFrame) -> ExpectedThreat:
        n = self.l * self.w
        shots = actions[actions.type_name.isin(SHOTS)]
        moves = actions[actions.type_name.isin(MOVES)]
        s_cell = self._cell(shots.start_x.to_numpy(), shots.start_y.to_numpy())
        m_cell = self._cell(moves.start_x.to_numpy(), moves.start_y.to_numpy())
        shot_n = np.bincount(s_cell, minlength=n).astype(float)
        goal_n = np.bincount(s_cell[(shots.result_name == "success").to_numpy()], minlength=n).astype(float)
        move_n = np.bincount(m_cell, minlength=n).astype(float)
        total = shot_n + move_n
        with np.errstate(invalid="ignore", divide="ignore"):
            self.p_shot = np.nan_to_num(shot_n / total)
            self.p_move = np.nan_to_num(move_n / total)
            self.p_goal = np.nan_to_num(goal_n / shot_n)
        ok = (moves.result_name == "success").to_numpy()
        end = self._cell(moves.end_x.to_numpy()[ok], moves.end_y.to_numpy()[ok])
        T = np.zeros((n, n))
        np.add.at(T, (m_cell[ok], end), 1.0)
        with np.errstate(invalid="ignore", divide="ignore"):
            self.T = np.nan_to_num(T / move_n[:, None])
        xt = np.zeros(n)
        self.iterations = 0
        while self.iterations < self.max_iter:
            self.iterations += 1
            new = self.p_shot * self.p_goal + self.p_move * (self.T @ xt)
            done = np.max(np.abs(new - xt)) < self.eps
            xt = new
            if done:
                break
        self.xT = xt
        return self

    @property
    def grid(self) -> np.ndarray:
        return self.xT.reshape(self.w, self.l)

    def rate(self, actions: pd.DataFrame) -> np.ndarray:
        """xT added by each action; NaN for non-moves and failed moves."""
        start = self._cell(actions.start_x.to_numpy(), actions.start_y.to_numpy())
        end = self._cell(actions.end_x.to_numpy(), actions.end_y.to_numpy())
        value = self.xT[end] - self.xT[start]
        ok = actions.type_name.isin(MOVES).to_numpy() & (actions.result_name == "success").to_numpy()
        return np.where(ok, value, np.nan)
