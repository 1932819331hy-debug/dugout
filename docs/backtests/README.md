# Backtests

Every model ships with a reproducible backtest. Regenerate all of them with:

```bash
uv run dugout-models backtest all
```

| Model | Report | Protocol | Headline result |
|---|---|---|---|
| Match predictor | [predictor.md](predictor.md) · [validation](predictor_validation.md) | Walk-forward, refit every ~4 gameweeks; design chosen on 2019-20..2023-24, tested once on 2024-25 and 2025-26 | Beats Elo on RPS, log loss and Brier in both test seasons; bookmaker closing odds remain better |
| Player quality (VAEP, xT) | [player_ratings.md](player_ratings.md) | VAEP probability models evaluated on held-out games | See report |
| Roles & similarity | [roles.md](roles.md) | Own-previous-season retrieval; bootstrap role stability | ~3x random retrieval; stability ARI ~0.7 |
| Manager fingerprint & tactical fit | [fingerprint.md](fingerprint.md) | Fit vs minutes share for players who changed club | **Fit does not predict minutes yet** (ρ ≈ 0.07, n.s.) |
| Valuation | [valuation.md](valuation.md) | Train < July 2024, test after | Beats "fee = market value" on MAE and median error |
| Transfer realism | [realism.md](realism.md) | Train summer windows 2015-23, test 2024-25 | Destination AUC 0.73; mobility AUC 0.58 (weak) |
| Injury risk | [injury.md](injury.md) | Train 2022-24, test 2024-25 | AUC ~0.61; not better calibrated than the base rate |
| Lineup optimiser | [lineup.md](lineup.md) | Trust weight chosen on 2023-24, test 2024-25 | Predicted XI 78% overlap vs 77% heuristic |

Negative and weak results are published on purpose: the site shows each model's evidence next to its output.
