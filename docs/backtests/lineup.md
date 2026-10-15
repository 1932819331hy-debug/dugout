# Lineup optimiser backtest

Generated 2026-10-15T15:56:37+00:00. Season 2024-25: for each club and match, the optimiser picks the best XI from players available that day (injury absences removed), using only data before kick-off.

| Method | Mean overlap with the actual XI | Team-matches |
|---|---|---|
| Strongest XI (quality only: ICT/90 x position fit, fatigue) | 50.6% | 658 |
| **Predicted XI** (quality + trust, weight 0.75) | 78.3% | 658 |
| Most minutes in the last 5 matches (heuristic) | 77.0% | 658 |

Trust weight 0.75 was chosen on 2023-24 (validation); this table is the 2024-25 test.
Trust = share of the last five matches' minutes. The strongest XI ignores managers' habits by design.
