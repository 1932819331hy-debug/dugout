# Match predictor backtest

Generated 2026-10-15T15:06:31+00:00. Protocol: walk-forward, refit every ~4 gameweeks (40 matches) on data strictly before the block. Training data from 2016-17 (football-data.co.uk results; Opta xG via FPL from 2022-23).

Lower is better. RPS = ranked probability score.

## 2019-20

| Model | RPS | Log loss | Brier | Matches |
|---|---|---|---|---|
| Bookmaker closing odds | 0.1984 | 0.9722 | 0.5744 | 380 |
| Stack + missing regulars (lineup-informed) | 0.1995 | 0.9735 | 0.5784 | 380 |
| **Stack: Elo + xG Dixon–Coles (pre-lineup) — dugout predictor** | 0.1995 | 0.9735 | 0.5784 | 380 |
| Stack with all features | 0.1998 | 0.9747 | 0.5788 | 380 |
| Boosted stack (pre-lineup) | 0.2006 | 0.9790 | 0.5811 | 380 |
| XGBoost on raw features | 0.2063 | 1.0080 | 0.5958 | 380 |
| Dixon–Coles, goals/xG blend (posterior mode) | 0.1986 | 0.9711 | 0.5768 | 380 |
| Dixon–Coles, goals (posterior mode) | 0.1986 | 0.9712 | 0.5767 | 380 |
| Elo baseline | 0.2020 | 0.9824 | 0.5841 | 380 |

Beats Elo on: rps, log_loss, brier

## 2020-21

| Model | RPS | Log loss | Brier | Matches |
|---|---|---|---|---|
| Bookmaker closing odds | 0.2111 | 0.9971 | 0.5921 | 380 |
| Stack + missing regulars (lineup-informed) | 0.2175 | 1.0247 | 0.6083 | 380 |
| **Stack: Elo + xG Dixon–Coles (pre-lineup) — dugout predictor** | 0.2175 | 1.0247 | 0.6083 | 380 |
| Stack with all features | 0.2175 | 1.0269 | 0.6092 | 380 |
| Boosted stack (pre-lineup) | 0.2184 | 1.0302 | 0.6107 | 380 |
| XGBoost on raw features | 0.2222 | 1.0502 | 0.6219 | 380 |
| Dixon–Coles, goals/xG blend (posterior mode) | 0.2156 | 1.0124 | 0.6032 | 380 |
| Dixon–Coles, goals (posterior mode) | 0.2159 | 1.0150 | 0.6045 | 380 |
| Elo baseline | 0.2226 | 1.0400 | 0.6162 | 380 |

Beats Elo on: rps, log_loss, brier

## 2021-22

| Model | RPS | Log loss | Brier | Matches |
|---|---|---|---|---|
| Bookmaker closing odds | 0.1890 | 0.9367 | 0.5543 | 380 |
| Stack + missing regulars (lineup-informed) | 0.1953 | 0.9561 | 0.5663 | 380 |
| **Stack: Elo + xG Dixon–Coles (pre-lineup) — dugout predictor** | 0.1953 | 0.9561 | 0.5663 | 380 |
| Stack with all features | 0.1969 | 0.9628 | 0.5703 | 380 |
| Boosted stack (pre-lineup) | 0.1936 | 0.9498 | 0.5624 | 380 |
| XGBoost on raw features | 0.1972 | 0.9681 | 0.5707 | 380 |
| Dixon–Coles, goals/xG blend (posterior mode) | 0.1947 | 0.9542 | 0.5648 | 380 |
| Dixon–Coles, goals (posterior mode) | 0.1947 | 0.9540 | 0.5648 | 380 |
| Elo baseline | 0.1946 | 0.9537 | 0.5648 | 380 |

Does not beat Elo.

## 2022-23

| Model | RPS | Log loss | Brier | Matches |
|---|---|---|---|---|
| Bookmaker closing odds | 0.1975 | 0.9622 | 0.5712 | 380 |
| Stack + missing regulars (lineup-informed) | 0.2088 | 1.0067 | 0.5975 | 380 |
| **Stack: Elo + xG Dixon–Coles (pre-lineup) — dugout predictor** | 0.2082 | 0.9950 | 0.5928 | 380 |
| Stack with all features | 0.2088 | 0.9954 | 0.5934 | 380 |
| Boosted stack (pre-lineup) | 0.2091 | 1.0006 | 0.5959 | 380 |
| XGBoost on raw features | 0.2180 | 1.0388 | 0.6206 | 380 |
| Dixon–Coles, goals/xG blend (posterior mode) | 0.2112 | 1.0019 | 0.5982 | 380 |
| Dixon–Coles, goals (posterior mode) | 0.2110 | 1.0023 | 0.5982 | 380 |
| Elo baseline | 0.2037 | 0.9812 | 0.5837 | 380 |

Does not beat Elo.

## 2023-24

| Model | RPS | Log loss | Brier | Matches |
|---|---|---|---|---|
| Bookmaker closing odds | 0.1805 | 0.8995 | 0.5258 | 380 |
| Stack + missing regulars (lineup-informed) | 0.1907 | 0.9318 | 0.5495 | 380 |
| **Stack: Elo + xG Dixon–Coles (pre-lineup) — dugout predictor** | 0.1888 | 0.9256 | 0.5450 | 380 |
| Stack with all features | 0.1900 | 0.9300 | 0.5484 | 380 |
| Boosted stack (pre-lineup) | 0.1912 | 0.9337 | 0.5509 | 380 |
| XGBoost on raw features | 0.1991 | 0.9732 | 0.5755 | 380 |
| Dixon–Coles, goals/xG blend (posterior mode) | 0.1902 | 0.9306 | 0.5472 | 380 |
| Dixon–Coles, goals (posterior mode) | 0.1904 | 0.9311 | 0.5484 | 380 |
| Elo baseline | 0.1895 | 0.9265 | 0.5460 | 380 |

Beats Elo on: rps, log_loss, brier

## Notes

- *Pre-lineup* uses only information available days before kick-off. *Lineup-informed* adds the share of each club's regular starters who did not start (known ~1 h before kick-off).
- Rest days count Premier League matches only (cup and European fixtures are not in the free data).
- Bookmaker probabilities remove the margin proportionally. Beating closing odds is not expected; they are shown as the ceiling.
