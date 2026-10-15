# Injury risk backtest

Generated 2026-10-15T15:40:00+00:00. Label: a new injury absence starts within 14 days of a match played. Train 2022-23 + 2023-24, test 2024-25.

Injury episodes: 2303. Test rows: 11559 (positive rate 2.76%).

| Model | AUC | Brier |
|---|---|---|
| logistic | 0.610 | 0.02692 |
| gradient_boosting | 0.629 | 0.02726 |
| base_rate | 0.500 | 0.02687 |

Logistic coefficients (standardised features): age 0.086, min_last3 0.13, min_28d -0.176, matches_14d 0.11, prev_episodes 0.149, days_since_episode -0.158, is_gk -0.121, is_def 0.119, is_mid -0.063, is_fwd 0.007, season_week -0.01

Data: API-Football free plan injury lists (2022–2024 seasons only); minutes from FPL; age/position from transfermarkt-datasets (CC0). Load counts Premier League minutes only.
