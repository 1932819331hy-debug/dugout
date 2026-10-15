# Transfer realism backtest

Generated 2026-10-15T16:05:27+00:00. transfermarkt-datasets (CC0); train summer windows 2015-2023, test 2024-2025.

| Factor | Model | Test AUC | Notes |
|---|---|---|---|
| Mobility (moves this summer?) | logistic | 0.583 | base rate 26.2%, 27481 player-summers |
| Destination (this club, given a move) | pairwise logistic | 0.732 | real buyer ranked first 47.4% vs random 16.5%, 2004 moves |
| Contract | prior weights | — | no historical contract data |
| News signal | prior weights | — | no historical news archive |

Mobility coefficients: age -0.735, log_mv 0.393, mv_change -0.076, minutes_share 0.007, rel_value 0.282, log_league 0.015

Destination coefficients: capacity_ratio 0.279, league_gap 0.116, club_value_gap 0.154, same_league 0.38, same_country 0.38

Wages are not modelled: no free, licensable wage data exists (Capology is not open).
