# Injury risk backtest

Generated 2026-10-18T18:50:53+00:00. Label: a new injury absence starts within 14 days of a match played. Train 2022-23 + 2023-24, test 2024-25.

## Premier League

Injury episodes: 2303. Test rows: 11559 (positive rate 2.76%).

| Model | AUC | Brier | Top-decile lift |
|---|---|---|---|
| logistic | 0.610 | 0.02697 | 2.32x |
| gradient_boosting | 0.637 | 0.02754 | 2.29x |
| gradient_boosting_calibrated | 0.622 | 0.02688 | 2.24x |
| base_rate | 0.500 | 0.02687 | 1.00x |

Logistic coefficients (standardised features): age 0.054, min_last3 0.175, min_28d -0.164, matches_14d 0.13, prev_episodes 0.176, days_since_episode -0.09, is_gk -0.117, is_def 0.116, is_mid -0.06, is_fwd 0.006, season_week -0.014, age2 0.07, min_7d -0.075, episodes_365 0.055, days_lost_365 -0.076, last_muscle 0.09

## Every league

Same label and split, per league. At-risk rows outside the Premier League are league matches played in transfermarkt-datasets appearances. *own*: logistic on the league's rows, all features. *pooled*: the same trained on all six leagues (league indicators). *history*: pooled, without recent minutes (age, position, injury record): what the site can score today outside the Premier League, where no current minutes source exists. *val AUC*: history model trained on 2022-23, ranked on 2023-24; a league is scored when it is at least 0.55 with 50+ new absences (decided before the test).

| League | Test rows | Positive rate | own AUC | own lift | pooled AUC | pooled lift | history AUC | history lift | Brier history / base | val AUC | Scored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Premier League | 11559 | 2.76% | 0.610 | 2.32x | 0.622 | 2.16x | 0.625 | 2.16x | 0.02675 / 0.02687 | 0.606 | yes |
| La Liga | 11899 | 4.42% | 0.636 | 2.00x | 0.638 | 2.07x | 0.631 | 2.09x | 0.04195 / 0.04227 | 0.635 | yes |
| Serie A | 11888 | 3.36% | 0.633 | 2.05x | 0.640 | 1.98x | 0.633 | 1.93x | 0.03220 / 0.03247 | 0.594 | yes |
| Bundesliga | 9527 | 3.31% | 0.591 | 1.75x | 0.599 | 1.52x | 0.585 | 1.40x | 0.03201 / 0.03200 | 0.607 | yes |
| Ligue 1 | 9413 | 2.97% | 0.550 | 1.36x | 0.629 | 1.75x | 0.623 | 1.82x | 0.02890 / 0.02897 | 0.617 | yes |
| Eredivisie | 9433 | 1.54% | 0.547 | 1.52x | 0.618 | 2.00x | 0.608 | 1.93x | 0.01514 / 0.01516 | 0.538 | no |

Live tiers: Premier League from the own model with FPL minutes (percentile among training rows); other scored leagues from the history model trained on all seasons, as a percentile among the league's current squad players (low below the median, moderate to the 80th, elevated to the 95th, high above). The free plan's injury lists stop with 2024-25, so outside the absences API-Football lists each night the record behind a tier is at least a season old: it says who has been injury-prone, not who is hurt now.

Data: API-Football free plan injury lists (2022–2024 seasons only, one call per league-season); minutes from FPL (Premier League) and transfermarkt-datasets appearances (other leagues); age/position from transfermarkt-datasets (CC0). Players matched to Transfermarkt by Reep, else by name within the club's squad that season (the lists give no date of birth).
