# Transfer valuation backtest

Generated 2026-10-15T16:21:09+00:00. Data: transfermarkt-datasets (CC0), transfers with a disclosed fee.

Train: 11770 transfers 2005-01-01 .. 2024-06-29. Test: 2024-07-01 .. 2026-09-03.

| Estimate | MAE (log fee) | Median abs % error | Within ±25% | Transfers |
|---|---|---|---|---|
| **dugout valuation** | 0.624 | 43.9% | 28.7% | 4702 |
| Market value at the time | 0.678 | 50.0% | 29.9% | 4702 |

Feature importance (split count): age 4277, log_mv 3221, log_to_league 2442, year 2081, log_from_league 2072, minutes_365 1168, apps_365 829, ga_p90_365 800, pos_Attack 316, same_league 258, pos_Defender 220, pos_Midfield 197, pos_Goalkeeper 119

Limitation: contract months remaining is not available historically, so it is not a feature.
