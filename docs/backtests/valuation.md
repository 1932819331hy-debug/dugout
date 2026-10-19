# Transfer valuation backtest

Generated 2026-10-18T20:17:20+00:00. Data: transfermarkt-datasets (CC0), transfers with a disclosed fee.

Train: 11770 transfers 2005-01-01 .. 2024-06-29. Test: 2024-07-01 .. 2026-09-03.

| Estimate | MAE (log fee) | Median abs % error | Within ±25% | Transfers |
|---|---|---|---|---|
| **dugout valuation** | 0.575 | 41.5% | 31.6% | 4702 |
| Market value at the time | 0.678 | 50.0% | 29.9% | 4702 |

By segment (MAE of log fee; fee / estimate is the median ratio, 1.00 = unbiased):

| Segment | Transfers | dugout | without league offsets | previous model | market value | fee / estimate (previous) |
|---|---|---|---|---|---|---|
| all | 4702 | 0.575 | 0.577 | 0.624 | 0.678 | 1.00 (1.08) |
| Premier League buyer | 371 | 0.412 | 0.413 | 0.516 | 0.525 | 0.96 (1.34) |
| Premier League to Premier League | 111 | 0.351 | 0.350 | 0.605 | 0.488 | 1.07 (1.65) |
| Premier League buyer, age 24 or under | 215 | 0.426 | 0.426 | 0.553 | 0.630 | 1.01 (1.38) |
| La Liga buyer | 175 | 0.531 | 0.529 | 0.608 | 0.641 | 1.07 (0.85) |
| La Liga to La Liga | 63 | 0.697 | 0.694 | 0.804 | 0.787 | 1.09 (0.84) |
| Serie A buyer | 345 | 0.498 | 0.501 | 0.528 | 0.527 | 1.02 (1.04) |
| Serie A to Serie A | 128 | 0.513 | 0.520 | 0.533 | 0.507 | 1.04 (1.07) |
| Bundesliga buyer | 269 | 0.563 | 0.589 | 0.624 | 0.608 | 0.99 (0.78) |
| Bundesliga to Bundesliga | 82 | 0.579 | 0.627 | 0.667 | 0.637 | 0.98 (0.73) |
| Ligue 1 buyer | 213 | 0.485 | 0.482 | 0.502 | 0.594 | 1.19 (1.07) |
| Ligue 1 to Ligue 1 | 53 | 0.508 | 0.504 | 0.493 | 0.639 | 1.21 (1.13) |
| Eredivisie buyer | 141 | 0.522 | 0.536 | 0.573 | 0.626 | 0.84 (1.13) |
| Eredivisie to Eredivisie | 46 | 0.512 | 0.516 | 0.542 | 0.639 | 0.99 (1.12) |

League offsets (log fee, buyers in each configured league; learned on 2022-07..2024-06 from a model fitted before 2022-07, shrunk by n / (n + 50); applied to every configured league, including the two where they made the test slightly worse): ES1 -0.109, FR1 -0.016, GB1 -0.008, IT1 +0.053, L1 -0.209, NL1 -0.070

The previous model regressed log(fee) on the transfer year; trees cannot extrapolate a year they have not seen, so it underpriced recent Premier League deals. Nationality (an English or homegrown premium) was tested as a feature and added nothing once club context is known; it is not used.

Feature importance (split count): log_to_cv 3091, age 2949, log_from_cv 2922, log_mv 2668, log_to_league 1991, log_from_league 1659, minutes_365 712, ga_p90_365 515, apps_365 476, pos_Attack 250, same_league 188, pos_Defender 172, pos_Midfield 137, to_pl 115, pos_Goalkeeper 113, pl_to_pl 42

Limitation: contract months remaining is not available historically, so it is not a feature.

Other leagues' buyers (the fair fee on those clubs' dossiers): read MAE against the market-value column and the median ratio; a ratio below 1.00 means fees came in under the estimate (it runs high there).

## Fee ranges (80%)

The site shows each fair fee with a likely range: split-conformal, calibrated on transfers 2022-07-01 .. 2024-07-01 scored by a model fitted before them (the same window and model as the league offsets), so the range never sees the test window. The ends are the equal-tailed interval of those errors (after the offsets), separately for each market-value band: fees for cheap players scatter much more than for stars. Ranges as multiples of the estimate, by band: under €2m ×0.27 – ×2.69, €2m to €5m ×0.30 – ×2.07, €5m to €15m ×0.42 – ×1.79, €15m or more ×0.51 – ×1.84.

Method chosen on validation (fitted and calibrated before 2023-07, scored on 2023-07..2024-06): the smallest worst gap between a value band's coverage and the target, then the narrower range. Training errors are the range used before (quantiles of the model's errors on its own training rows): too narrow out of sample, worst for cheap players.

| Method | Validation: inside | worst value band (gap) | median width | Test: inside | worst band gap |
|---|---|---|---|---|---|
| training errors (previous range) | 72.6% | 0.168 | €2.2m | 76.0% | 0.136 |
| pooled | 81.1% | 0.108 | €2.7m | 83.2% | 0.163 |
| by buyer league | 79.1% | 0.098 | €2.6m | 80.6% | 0.104 |
| value bands (3) | 80.7% | 0.040 | €2.9m | 82.6% | 0.097 |
| value bands (4) (shipped) | 80.5% | 0.030 | €2.9m | 82.9% | 0.097 |
| value bands (5) | 80.3% | 0.098 | €2.7m | 82.5% | 0.090 |

Test window, shipped range, by segment (below / above: fee under the low end / over the high end):

| Segment | Transfers | Inside the range | Below it | Above it | Median width | Range / estimate (median) |
|---|---|---|---|---|---|---|
| all | 4702 | 82.9% | 7.5% | 9.6% | €2.9m | ×0.27 – ×2.69 |
| Premier League buyer | 371 | 86.3% | 5.9% | 7.8% | €19.7m | ×0.42 – ×1.84 |
| Premier League to Premier League | 111 | 88.3% | 5.4% | 6.3% | €26.2m | ×0.51 – ×1.84 |
| Premier League buyer, age 24 or under | 215 | 84.2% | 4.2% | 11.6% | €20.3m | ×0.42 – ×1.84 |
| La Liga buyer | 175 | 78.3% | 8.0% | 13.7% | €5.3m | ×0.30 – ×2.07 |
| La Liga to La Liga | 63 | 73.0% | 12.7% | 14.3% | €4.4m | ×0.30 – ×2.07 |
| Serie A buyer | 345 | 83.2% | 8.7% | 8.1% | €7.4m | ×0.30 – ×2.07 |
| Serie A to Serie A | 128 | 79.7% | 10.9% | 9.4% | €8.1m | ×0.42 – ×1.84 |
| Bundesliga buyer | 269 | 78.1% | 9.7% | 12.3% | €6.0m | ×0.42 – ×1.84 |
| Bundesliga to Bundesliga | 82 | 80.5% | 11.0% | 8.5% | €5.9m | ×0.42 – ×1.84 |
| Ligue 1 buyer | 213 | 81.7% | 4.7% | 13.6% | €7.2m | ×0.42 – ×1.84 |
| Ligue 1 to Ligue 1 | 53 | 73.6% | 3.8% | 22.6% | €8.0m | ×0.42 – ×1.84 |
| Eredivisie buyer | 141 | 90.1% | 7.1% | 2.8% | €3.0m | ×0.27 – ×2.69 |
| Eredivisie to Eredivisie | 46 | 93.5% | 2.2% | 4.3% | €1.9m | ×0.27 – ×2.69 |

By market value at the time of the transfer:

| Segment | Transfers | Inside the range | Below it | Above it | Median width | Range / estimate (median) |
|---|---|---|---|---|---|---|
| under €1m | 1656 | 80.7% | 9.4% | 9.9% | €1.0m | ×0.27 – ×2.69 |
| €1m to €3m | 1260 | 86.6% | 6.2% | 7.2% | €2.6m | ×0.27 – ×2.69 |
| €3m to €10m | 1160 | 80.7% | 6.8% | 12.5% | €6.1m | ×0.30 – ×2.07 |
| €10m to €30m | 490 | 84.1% | 6.3% | 9.6% | €19.3m | ×0.51 – ×1.84 |
| €30m or more | 136 | 89.7% | 5.9% | 4.4% | €53.3m | ×0.51 – ×1.84 |

Reading: overall 82.9% of test fees landed inside, a little over the target: the calibration errors come from a model fitted two years earlier on less data, so the range is slightly conservative. Too narrow (under 75%): La Liga to La Liga 73%, Ligue 1 to Ligue 1 74%. Wider than needed (over 85%): Premier League buyer 86%, Premier League to Premier League 88%, Eredivisie buyer 90%, Eredivisie to Eredivisie 93%, €1m to €3m 87%, €30m or more 90%.

### Fresh holdout: summer 2026 (Wikipedia transfer lists)

Fees from `wiki_transfers` (Wikipedia's transfer lists, Transfermarkt ids via Wikidata) dated from 2026-06-01 for moves transfermarkt-datasets does not list, scored by a model fitted and calibrated on transfers before 2026-06-01. Mostly English pages (Premier League and Championship buyers). MAE (log fee): dugout 0.433, market value 0.482 (118 transfers).

| Segment | Transfers | Inside the range | Below it | Above it | Median width | Range / estimate (median) |
|---|---|---|---|---|---|---|
| all | 118 | 76.3% | 8.5% | 15.3% | €27.2m | ×0.64 – ×1.71 |
| Premier League buyer | 76 | 75.0% | 10.5% | 14.5% | €32.4m | ×0.64 – ×1.71 |
| other buyers | 42 | 78.6% | 4.8% | 16.7% | €16.2m | ×0.45 – ×1.92 |
| under €1m | 3 | 33.3% | 0.0% | 66.7% | €1.4m | ×0.30 – ×2.55 |
| €1m to €3m | 10 | 50.0% | 0.0% | 50.0% | €2.9m | ×0.37 – ×2.33 |
| €3m to €10m | 22 | 63.6% | 4.5% | 31.8% | €8.3m | ×0.45 – ×1.92 |
| €10m to €30m | 46 | 82.6% | 10.9% | 6.5% | €27.0m | ×0.64 – ×1.71 |
| €30m or more | 37 | 86.5% | 10.8% | 2.7% | €66.1m | ×0.64 – ×1.71 |

With 118 transfers one standard error is about 3.7%; the bands under €10m hold only a few dozen moves between them. Misses are mostly fees above the range.
