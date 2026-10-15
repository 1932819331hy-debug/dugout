# Transfer realism backtest

Generated 2026-10-15T16:40:24+00:00. transfermarkt-datasets (CC0); train summer windows 2015-2023, test 2024-2025.

| Factor | Model | Test AUC | Notes |
|---|---|---|---|
| Mobility (sold for a fee this summer?) | logistic | 0.753 | Brier 0.0687 vs base rate 0.0733; 7.7% sold, 27481 player-summers |
| Mobility | gradient boosting | 0.753 | Brier 0.0669 |
| Destination (this club, given a move) | pairwise logistic | 0.732 | real buyer ranked first 47.4% vs random 16.5%, 2004 moves |
| Contract | prior weights | — | no historical contract data |
| News signal | prior weights | — | no historical news archive |

Mobility coefficients: age -0.783, age2 -0.25, log_mv 0.616, mv_change 0.113, minutes_share -0.004, share_change 0.055, rel_value 0.329, log_league 0.033, tenure 0.136, peak_ratio 0.219, relegated 0.086

Destination coefficients: capacity_ratio 0.279, league_gap 0.116, club_value_gap 0.154, same_league 0.38, same_country 0.38

Wages are not modelled: no free, licensable wage data exists (Capology is not open).
