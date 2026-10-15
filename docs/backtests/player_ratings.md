# Player quality: VAEP and xT

Generated 2026-10-15T16:20:28+00:00. Open event data: StatsBomb (PL 2015/16) and Wyscout public (PL 2017/18), converted to SPADL.

## VAEP probability models (held-out games: 380, trained on 380)

| Label | AUC | Brier | Brier (base rate) | Positive rate |
|---|---|---|---|---|
| scores within 10 actions | 0.748 | 0.0109 | 0.0125 | 0.0127 |
| concedes within 10 actions | 0.778 | 0.0033 | 0.0034 | 0.0034 |

xT: 16 x 12 grid, converged in 32 iterations; max cell value 0.050.

## Top 15 players by VAEP per 90 (min 900 minutes)

| Player | Dataset | Minutes | VAEP/90 | Offensive/90 | Defensive/90 | xT/90 |
|---|---|---|---|---|---|---|
| Mohamed  Salah Ghaly | wyscout_public | 3065 | 0.786 | 0.788 | -0.002 | 0.062 |
| Philippe Coutinho Correia | wyscout_public | 1159 | 0.661 | 0.687 | -0.027 | 0.139 |
| Sergio Leonel Agüero del Castillo | statsbomb | 2462 | 0.643 | 0.640 | 0.003 | 0.045 |
| Daniel Andre Sturridge | statsbomb | 1038 | 0.553 | 0.573 | -0.019 | 0.025 |
| Dimitri Payet | statsbomb | 2740 | 0.534 | 0.528 | 0.005 | 0.137 |
| Anthony Martial | wyscout_public | 1684 | 0.519 | 0.521 | -0.002 | 0.059 |
| Pierre-Emerick Aubameyang | wyscout_public | 1121 | 0.516 | 0.528 | -0.012 | 0.018 |
| Sergio Leonel Agüero del Castillo | wyscout_public | 2096 | 0.508 | 0.564 | -0.056 | 0.022 |
| David Josué Jiménez Silva | wyscout_public | 2577 | 0.498 | 0.490 | 0.007 | 0.081 |
| Harry Kane | wyscout_public | 3257 | 0.492 | 0.509 | -0.018 | 0.014 |
| Eden Hazard | wyscout_public | 2551 | 0.490 | 0.492 | -0.003 | 0.074 |
| Jamie Vardy | statsbomb | 3314 | 0.480 | 0.506 | -0.026 | 0.037 |
| Heung-Min Son | wyscout_public | 2424 | 0.462 | 0.468 | -0.006 | 0.033 |
| Riyad Mahrez | statsbomb | 3148 | 0.460 | 0.481 | -0.021 | 0.075 |
| Riyad Mahrez | wyscout_public | 3127 | 0.457 | 0.448 | 0.009 | 0.089 |
