# Injury risk backtest

Generated 2026-10-15T16:42:06+00:00. Label: a new injury absence starts within 14 days of a match played. Train 2022-23 + 2023-24, test 2024-25.

Injury episodes: 2303. Test rows: 11559 (positive rate 2.76%).

| Model | AUC | Brier | Top-decile lift |
|---|---|---|---|
| logistic | 0.610 | 0.02697 | 2.32x |
| gradient_boosting | 0.637 | 0.02754 | 2.29x |
| gradient_boosting_calibrated | 0.622 | 0.02688 | 2.24x |
| base_rate | 0.500 | 0.02687 | 1.00x |

Logistic coefficients (standardised features): age 0.054, min_last3 0.175, min_28d -0.164, matches_14d 0.13, prev_episodes 0.176, days_since_episode -0.09, is_gk -0.117, is_def 0.116, is_mid -0.06, is_fwd 0.006, season_week -0.014, age2 0.07, min_7d -0.075, episodes_365 0.055, days_lost_365 -0.076, last_muscle 0.09

Data: API-Football free plan injury lists (2022–2024 seasons only); minutes from FPL; age/position from transfermarkt-datasets (CC0). Load counts Premier League minutes only.
