# Fact-Check NLI benchmark

Generated 2026-10-15T17:38:45+00:00. 48 hand-labelled football premise/claim pairs ({'entailment': 22, 'neutral': 8, 'contradiction': 18}). Decision thresholds: entail p >= 0.7, contradict p >= 0.7.

| Model | Accuracy | Entail precision | Entail recall | False verifications | Contra precision | Contra recall | s/pair (CPU) |
|---|---|---|---|---|---|---|---|
| MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli | 0.83 | 1.00 | 0.91 | 0 | 0.80 | 0.89 | 1.12 |
| MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli | 0.85 | 1.00 | 0.91 | 0 | 0.77 | 0.94 | 3.567 |

False verifications (a non-entailed claim passing the entail threshold) are what matter most.
