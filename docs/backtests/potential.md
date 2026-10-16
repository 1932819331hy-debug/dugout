# Player potential backtest

Generated 2026-10-15T18:44:18+00:00. Target: log market value h years after a 1 June snapshot (transfermarkt-datasets, CC0). Time split: every training target is dated before the test snapshots.

## 2 years ahead

Train snapshots 2012-2021 (133373 player-years); test 2023-2024. 30% of test players had no valuation 2 years on and are not scored.

| Method | Players | MAE (log) | Median abs. % error | Spearman | 10-90% band coverage |
|---|---|---|---|---|---|
| **Potential model** | 27699 | 0.597 | 42% | 0.809 | 76% |
| Age curve (median change by age) | 27699 | 0.653 | 45% | 0.800 | — |
| Persistence (value unchanged) | 27699 | 0.780 | 53% | 0.729 | — |
| **Potential model**, age 21 or under | 4789 | 0.894 | 61% | 0.711 | 73% |
| Age curve, age 21 or under | 4789 | 0.979 | 67% | 0.690 | — |

Most used features: log_league, log_mv, age, minutes_share, age2, height

## 4 years ahead

Train snapshots 2010-2019 (99066 player-years); test 2021-2022. 48% of test players had no valuation 4 years on and are not scored.

| Method | Players | MAE (log) | Median abs. % error | Spearman | 10-90% band coverage |
|---|---|---|---|---|---|
| **Potential model** | 23072 | 0.758 | 54% | 0.719 | 76% |
| Age curve (median change by age) | 23072 | 0.878 | 60% | 0.707 | — |
| Persistence (value unchanged) | 23072 | 1.148 | 75% | 0.533 | — |
| **Potential model**, age 21 or under | 4637 | 1.032 | 69% | 0.581 | 76% |
| Age curve, age 21 or under | 4637 | 1.151 | 73% | 0.575 | — |

Most used features: log_league, log_mv, height, age, age2, mv_change_2y

Market value mixes ability with age, contract and hype. The dossier shows the projection as a level (compared with current Premier League players) next to its 10-90% band, never alone.
