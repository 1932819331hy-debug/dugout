"""Evaluation on 50 hand-labelled questions (`eval/questions.yaml`).

Metrics
  routing accuracy        labelled specialists are all in the route
  answer recall           labelled (entity, metric) facts cited in *published* text / labelled facts
  claim recall            labelled non-numeric claims published as verified / labelled claims
  citation rate           published claims carrying a ledger id or a verified source / published factual claims
  untraceable-number rate numbers in published text not filled from the ledger / numbers published (target 0)
  refusal accuracy        unanswerable questions answered without the asked-for metric
  LLM draft stray-number rate: how often the LLM itself tried to write a number (caught before publication)
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

import yaml
from dugout_agents.graph import Context, run
from dugout_verify.auditor import stray_numbers


def load_questions(name: str = "questions") -> list[dict]:
    return yaml.safe_load(files("dugout_agents").joinpath(f"eval/{name}.yaml").read_text(encoding="utf-8"))


def _entity_matches(ctx: Context, entity_id: str, want: str) -> bool:
    if want == "any":
        return True
    names = [ctx.toolbox.name(entity_id), *ctx.toolbox.aliases.get(entity_id, [])]
    return any(want.lower() in n.lower() for n in names)


def score_question(q: dict, state, ctx: Context) -> dict:
    sections = [*state["sections"], state["summary"]]
    published = [s for s in sections if s.status == "published"]
    cited = [ctx.ledger.get(e) for s in published for e in s.cited]
    claims = [
        c for s in published for c in (s.factcheck or {}).get("claims", []) if c["status"] == "verified"
    ]
    res: dict = {"id": q["id"], "question": q["question"], "route": state["agents"]}
    if q.get("agents"):
        res["routed_ok"] = set(q["agents"]) <= set(state["agents"])
    hits = []
    for e in q.get("expect", []):
        metrics = e["metric"] if isinstance(e["metric"], list) else [e["metric"]]
        hits.append(
            any(ev.metric in metrics and _entity_matches(ctx, ev.entity_id, e["entity"]) for ev in cited)
        )
    res["expect_hits"] = hits
    chits = []
    for c in q.get("claims", []):
        chits.append(
            any(
                (
                    c["type"] == "any"
                    or cl["type"] == c["type"]
                    or (c["type"] == "injury" and cl["type"] == "stat")
                )
                and (c["entity"] == "any" or c["entity"].split()[-1].lower() in cl["text"].lower())
                and cl["type"] != "analysis"
                for cl in claims
            )
        )
    res["claim_hits"] = chits
    if "no_stat" in q:
        res["refusal_ok"] = not any(ev.metric in q["no_stat"] for ev in cited)
    # published numbers and their traceability
    text = " ".join(s.published_template for s in published)
    res["numbers_published"] = sum(len(s.cited) for s in published)
    res["numbers_untraceable"] = len(stray_numbers(text, ctx.allowed_names()))
    factual = [
        c
        for s in published
        for c in (s.factcheck or {}).get("claims", [])
        if c["status"] != "analysis" and any(c["text"] in s.published_template for _ in [0])
    ]
    res["claims_published"] = len(factual)
    res["claims_cited"] = sum(1 for c in factual if "{{stat:" in c["text"] or c.get("support"))
    res["writers"] = [s.writer for s in sections]
    res["llm_draft_stray"] = sum(
        1
        for s in sections
        for a in s.attempts
        if any("numbers written directly" in e for e in a.get("errors", []))
    )
    res["llm_attempts"] = sum(len(s.attempts) for s in sections)
    res["withheld"] = sum(len(s.withheld) for s in sections)
    res["answer"] = {s.title: s.text for s in published}
    return res


def summarise(rows: list[dict]) -> dict:
    def rate(num, den):
        return round(num / den, 3) if den else None

    routed = [r["routed_ok"] for r in rows if "routed_ok" in r]
    hits = [h for r in rows for h in r["expect_hits"]]
    chits = [h for r in rows for h in r["claim_hits"]]
    refusals = [r["refusal_ok"] for r in rows if "refusal_ok" in r]
    pub = sum(r["numbers_published"] for r in rows)
    untr = sum(r["numbers_untraceable"] for r in rows)
    writers = [w for r in rows for w in r["writers"]]
    return {
        "questions": len(rows),
        "routing_accuracy": rate(sum(routed), len(routed)),
        "answer_recall": rate(sum(hits), len(hits)),
        "claim_recall": rate(sum(chits), len(chits)),
        "refusal_accuracy": rate(sum(refusals), len(refusals)),
        "citation_rate": rate(sum(r["claims_cited"] for r in rows), sum(r["claims_published"] for r in rows)),
        "numbers_published": pub,
        "untraceable_number_rate": rate(untr, pub + untr) if (pub + untr) else 0.0,
        "llm_sections": sum(w.startswith("llm") for w in writers),
        "template_sections": sum(w == "template" for w in writers),
        "llm_attempts_with_stray_numbers": sum(r["llm_draft_stray"] for r in rows),
        "llm_attempts": sum(r["llm_attempts"] for r in rows),
        "sentences_withheld": sum(r["withheld"] for r in rows),
    }


def run_eval(
    ctx: Context,
    out_dir: Path | None = None,
    limit: int | None = None,
    name: str = "agents_eval",
    question_set: str = "questions",
) -> dict:
    qs = load_questions(question_set)[:limit]
    rows = []
    t0 = time.time()
    for q in qs:
        state = run(ctx, q["question"], q.get("club", "liverpool"))
        rows.append(score_question(q, state, ctx))
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "llm": ctx.llm.name if ctx.llm else None,
        "runtime_seconds": round(time.time() - t0),
        "summary": summarise(rows),
        "questions": rows,
    }
    if out_dir:
        write_report(report, out_dir, name)
    return report


def write_report(report: dict, out_dir: Path, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    s = report["summary"]
    lines = [
        f"# Agent evaluation ({report['llm'] or 'templates only'})",
        "",
        f"Generated {report['generated_at']}; {s['questions']} hand-labelled questions "
        "(`packages/agents/src/dugout_agents/eval/questions.yaml`); runtime "
        f"{report['runtime_seconds']} s.",
        "",
        "| Metric | Value |",
        "|---|---|",
        *[f"| {k.replace('_', ' ')} | {v} |" for k, v in s.items()],
        "",
        "## Per question",
        "",
        "| id | route | answered | refusal | numbers | withheld | writer |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in report["questions"]:
        ans = r["expect_hits"] + r["claim_hits"]
        lines.append(
            f"| {r['id']} | {', '.join(r['route'])}{'' if r.get('routed_ok', True) else ' ✗'} | "
            f"{sum(ans)}/{len(ans)} | {r.get('refusal_ok', '')} | {r['numbers_published']} | {r['withheld']} | "
            f"{', '.join(sorted(set(r['writers'])))} |"
        )
    (out_dir / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
