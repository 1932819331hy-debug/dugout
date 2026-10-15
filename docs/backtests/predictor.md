# Match predictor backtest

Generated 2026-10-15T15:30:50+00:00. Protocol: walk-forward, refit every ~4 gameweeks (40 matches) on data strictly before the block. Training data from 2016-17 (football-data.co.uk results; Opta xG via FPL from 2022-23).

Lower is better. RPS = ranked probability score.

## 2024-25

| Model | RPS | Log loss | Brier | Matches |
|---|---|---|---|---|
| Bookmaker closing odds | 0.1961 | 0.9664 | 0.5751 | 380 |
| Stack + missing regulars (lineup-informed) | 0.1953 | 0.9654 | 0.5740 | 380 |
| **Stack: Elo + xG Dixon–Coles (pre-lineup) — dugout predictor** | 0.1996 | 0.9781 | 0.5834 | 380 |
| Stack with all features | 0.1978 | 0.9742 | 0.5804 | 380 |
| Boosted stack (pre-lineup) | 0.1969 | 0.9679 | 0.5760 | 380 |
| XGBoost on raw features | 0.2010 | 0.9862 | 0.5875 | 380 |
| Dixon–Coles, goals/xG blend (posterior mode) | 0.1992 | 0.9771 | 0.5817 | 380 |
| Dixon–Coles, goals (Bayesian, NUTS) | 0.2017 | 0.9840 | 0.5866 | 380 |
| Dixon–Coles, goals (posterior mode) | 0.2025 | 0.9854 | 0.5884 | 380 |
| Elo baseline | 0.2016 | 0.9833 | 0.5879 | 380 |

Beats Elo on: rps, log_loss, brier

## 2025-26

| Model | RPS | Log loss | Brier | Matches |
|---|---|---|---|---|
| Bookmaker closing odds | 0.2051 | 1.0139 | 0.6092 | 380 |
| Stack + missing regulars (lineup-informed) | 0.2114 | 1.0343 | 0.6237 | 380 |
| **Stack: Elo + xG Dixon–Coles (pre-lineup) — dugout predictor** | 0.2107 | 1.0322 | 0.6218 | 380 |
| Stack with all features | 0.2104 | 1.0288 | 0.6199 | 380 |
| Boosted stack (pre-lineup) | 0.2101 | 1.0304 | 0.6206 | 380 |
| XGBoost on raw features | 0.2140 | 1.0507 | 0.6311 | 380 |
| Dixon–Coles, goals/xG blend (posterior mode) | 0.2087 | 1.0279 | 0.6172 | 380 |
| Dixon–Coles, goals (Bayesian, NUTS) | 0.2106 | 1.0320 | 0.6208 | 380 |
| Dixon–Coles, goals (posterior mode) | 0.2089 | 1.0266 | 0.6170 | 380 |
| Elo baseline | 0.2139 | 1.0419 | 0.6290 | 380 |

Beats Elo on: rps, log_loss, brier

## Notes

- *Pre-lineup* uses only information available days before kick-off. *Lineup-informed* adds the share of each club's regular starters who did not start (known ~1 h before kick-off).
- Rest days count Premier League matches only (cup and European fixtures are not in the free data).
- Bookmaker probabilities remove the margin proportionally. Beating closing odds is not expected; they are shown as the ceiling.
