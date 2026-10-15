# FootballBERT player embeddings: evaluated, not adopted

Model: `achadj/footballbert-base` (Apache-2.0; RisingBALLER, arXiv:2410.00943). Loaded safely: only
`model.safetensors` and JSON vocabularies; the id-to-name pickle is read with an unpickler that refuses every
class lookup (static inspection showed only dicts and strings); the repository's custom code is never run.
Player vectors = the tied masked-player-prediction weights (99,944 x 256). Name matching (exact, unique) maps
542 / 667 current Premier League players and 28,745 / 50,149 transfermarkt-datasets players.

## What the vectors encode

Nearest neighbours are mostly former team-mates: Florian Wirtz -> Havertz, Adli, Frimpong, Hincapié, Palacios
(Leverkusen); Virgil van Dijk -> Gomez, Robertson, Dunk, Gakpo, Tarkowski. Trained on lineups, the model learns
*who plays with whom*, not *how a player plays*.

## Does embedding "fit" predict a newcomer's playing time?

Fit = cosine similarity between a newcomer and the minutes-weighted centroid of the players the buying club used
at his position the previous season. Outcome = his minutes share at the new club. Summer transfers 2016-2025,
transfermarkt-datasets. Controls: previous minutes share, market value. Cross-validation grouped by season.

| Variant | Transfers | Spearman (fit, minutes share) | CV R² without fit | CV R² with fit |
|---|---|---|---|---|
| Naive | 8,045 | 0.123 (p ≈ 1e-28) | 0.0313 | 0.0339 |
| **Leakage-guarded** (centroid built only from players who had left, so the newcomer never lined up with them there) | 4,966 | 0.028 (p = 0.045) | 0.0482 | 0.0479 |

The naive result is leakage: FootballBERT was trained on lineups through 2025-26, so it has already seen the
newcomer playing alongside his new team-mates. With the guard, the signal disappears.

**Decision:** not used for similarity or tactical fit. The safe loader (`dugout_models.embeddings`) and the
experiment (`python -m dugout_models.experiments.footballbert_fit [--no-guard]`) stay in the repo.
