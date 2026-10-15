# Roles and similarity

Generated 2026-10-15T15:37:54+00:00. Per-90 FPL/Opta profiles, players with >= 900 minutes in a season. Features: xg, xa, goals, assists, threat, creativity, influence; plus tackles, recoveries, cbi from 2025-26 (when FPL started tracking them).

## Similarity: does a player's profile find his own previous season?

| Seasons | Players | Top-1 | Top-5 |
|---|---|---|---|
| 2022-23 -> 2023-24 | 116 | 9.5% | 38.8% |
| 2023-24 -> 2024-25 | 148 | 13.5% | 38.5% |
| 2024-25 -> 2025-26 | 171 | 9.9% | 36.3% |
| random guess | | 3.4% | 17.1% |

## Roles (2025-26)

Bootstrap stability (mean adjusted Rand index, 20 resamples): 0.71

| Position: role | Players |
|---|---|
| DEF: creative full-back | 52 |
| DEF: stopper centre-back | 49 |
| FWD: creative forward | 5 |
| FWD: penalty-box striker | 9 |
| FWD: pressing forward | 6 |
| FWD: target forward | 6 |
| GK: goalkeeper | 19 |
| MID: attacking midfielder | 69 |
| MID: holding midfielder | 60 |

Limitation: FPL/Opta box-score profiles cannot see positioning or passing networks; event or tracking data would separate roles more finely. Player embeddings (FootballBERT) are pending a decision on loading third-party weights.
