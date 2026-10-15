"""Benchmark NLI models on hand-labelled football claims (`data/nli_pairs.jsonl`).

What matters for Fact-Check is not accuracy but *false verification*: a neutral or contradicted claim scored as
entailed would publish something unsupported. So the headline numbers are precision of the entailment decision
(p >= ENTAIL) and of the contradiction decision (p >= CONTRA), plus CPU latency.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

import numpy as np

from dugout_verify.factcheck import CONTRA, ENTAIL
from dugout_verify.nli import NLI_MODELS, DebertaNLI

LABELS = ["entailment", "neutral", "contradiction"]


def load_pairs() -> list[dict]:
    text = files("dugout_verify").joinpath("data/nli_pairs.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def evaluate(model: DebertaNLI, pairs: list[dict]) -> dict:
    model.scores(["warm up"], "warm up")
    t0 = time.perf_counter()
    probs = np.vstack([model.scores([p["premise"]], p["hypothesis"]) for p in pairs])
    secs = (time.perf_counter() - t0) / len(pairs)
    y = np.array([LABELS.index(p["label"]) for p in pairs])
    ent, con = probs[:, 0] >= ENTAIL, probs[:, 2] >= CONTRA

    def prec(mask, cls):
        return float((y[mask] == cls).mean()) if mask.any() else None

    return {
        "accuracy": float((probs.argmax(1) == y).mean()),
        "entail_precision": prec(ent, 0),
        "entail_recall": float(ent[y == 0].mean()),
        "false_verifications": int((ent & (y != 0)).sum()),
        "contra_precision": prec(con, 2),
        "contra_recall": float(con[y == 2].mean()),
        "seconds_per_pair_cpu": round(secs, 3),
        "errors": [
            {**pairs[i], "probs": [round(float(x), 2) for x in probs[i]]}
            for i in np.where(probs.argmax(1) != y)[0]
        ],
    }


def run(out_dir: Path | None = None, sizes: tuple[str, ...] = ("base", "large")) -> dict:
    pairs = load_pairs()
    res = {s: evaluate(DebertaNLI(s), pairs) for s in sizes}
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pairs": len(pairs),
        "label_counts": {k: sum(p["label"] == k for p in pairs) for k in LABELS},
        "thresholds": {"entail": ENTAIL, "contradict": CONTRA},
        "models": {s: NLI_MODELS[s].repo for s in sizes},
        "results": res,
    }
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "factcheck_nli.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        lines = [
            "# Fact-Check NLI benchmark",
            "",
            f"Generated {report['generated_at']}. {len(pairs)} hand-labelled football premise/claim pairs "
            f"({report['label_counts']}). Decision thresholds: entail p >= {ENTAIL}, contradict p >= {CONTRA}.",
            "",
            "| Model | Accuracy | Entail precision | Entail recall | False verifications | Contra precision | "
            "Contra recall | s/pair (CPU) |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for s, r in res.items():
            lines.append(
                f"| {NLI_MODELS[s].repo} | {r['accuracy']:.2f} | {r['entail_precision']:.2f} | "
                f"{r['entail_recall']:.2f} | {r['false_verifications']} | {r['contra_precision'] or 0:.2f} | "
                f"{r['contra_recall']:.2f} | {r['seconds_per_pair_cpu']} |"
            )
        lines += [
            "",
            "False verifications (a non-entailed claim passing the entail threshold) are what matter most.",
        ]
        (out_dir / "factcheck_nli.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    print(
        json.dumps(
            {k: {m: v for m, v in r.items() if m != "errors"} for k, r in run(out)["results"].items()},
            indent=2,
        )
    )
