"""`data/clubs/<slug>.json`: the verified club dossier the website reads.

Text is stored as *segments* so the site can make every number hoverable: {"text": ...} or {"stat": id, "display":
...}. Each cited stat carries value, source, URL, fetch time and verification status. Only sections that passed
the Stat Auditor and Fact-Check are included; withheld material is listed (without numbers) for transparency.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dugout_agents.facts import MODEL_DOCS
from dugout_agents.graph import Context, Section, State, run
from dugout_agents.specialists import SPECIALISTS
from dugout_verify.ledger import PLACEHOLDER, format_value

SCHEMA = "dugout.club/1"


def segments(template: str, ctx: Context) -> list[dict]:
    out: list[dict] = []
    pos = 0
    for m in PLACEHOLDER.finditer(template):
        if m.start() > pos:
            out.append({"text": template[pos : m.start()]})
        ev = ctx.ledger.get(m.group(1))
        out.append({"stat": m.group(1), "display": format_value(ev, m.group(2))})
        pos = m.end()
    if pos < len(template):
        out.append({"text": template[pos:]})
    return out


def _strip_numbers(text: str) -> str:
    return PLACEHOLDER.sub("[number]", text)


def section_json(sec: Section, ctx: Context) -> dict:
    claims = []
    for c in (sec.factcheck or {}).get("claims", []):
        if c["status"] not in ("verified", "analysis"):
            continue
        claims.append(
            {
                "segments": segments(c["text"], ctx),
                "type": c["type"],
                "status": c["status"],
                "reason": c["reason"],
                "sources": [
                    {k: s.get(k) for k in ("outlet", "tier", "url", "official")} for s in c.get("support", [])
                ],
            }
        )
    return {
        "agent": sec.agent,
        "title": sec.title,
        "question": sec.question,
        "status": sec.status,
        "writer": sec.writer,
        "claims": claims if sec.status == "published" else [],
        "withheld": [{**w, "text": _strip_numbers(w["text"])} for w in sec.withheld],
    }


def stat_json(eid: str, ctx: Context, status: dict[str, str], cross: dict[str, list]) -> dict:
    ev = ctx.ledger.get(eid)
    return {
        "value": ev.value,
        "display": format_value(ev, None),
        "unit": ev.unit,
        "metric": ev.metric,
        "entity_type": ev.entity_type,
        "entity_id": ev.entity_id,
        "entity_name": ctx.toolbox.name(ev.entity_id),
        "source": ev.source,
        "source_url": ev.source_url,
        "source_tier": ev.source_tier,
        "fetched_at": ev.fetched_at.isoformat(),
        "query_kind": ev.query.get("kind"),
        "status": status.get(eid, "unknown"),
        "cross_checks": cross.get(eid, []),
    }


def build(ctx: Context, club: str) -> tuple[dict, State]:
    state = run(ctx, "", club, agents=list(SPECIALISTS))
    sections = sorted(state["sections"], key=lambda s: list(SPECIALISTS).index(s.agent))
    everything = [state["summary"], *sections]
    published = [s for s in everything if s.status == "published"]
    status: dict[str, str] = {}
    cross: dict[str, list] = {}
    totals = {"numbers_total": 0, "numbers_untraceable": 0}
    fc_counts: dict[str, int] = {}
    for s in everything:
        if s.audit:
            status.update(s.audit["stat_status"])
            cross.update(s.audit["cross_checks"])
        if s.status == "published":
            totals["numbers_total"] += len(s.cited)
        for k, v in ((s.factcheck or {}).get("counts") or {}).items():
            fc_counts[k] = fc_counts.get(k, 0) + v
    cited = sorted({e for s in published for e in s.cited})
    doc: dict[str, Any] = {
        "schema": SCHEMA,
        "club": {"slug": club, "name": ctx.toolbox.name(club), "season": ctx.toolbox.season},
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "data_as_of": ctx.toolbox.now.isoformat(timespec="seconds"),
        "llm": ctx.llm.name if ctx.llm else None,
        "summary": section_json(state["summary"], ctx),
        "sections": [section_json(s, ctx) for s in sections],
        "stats": {e: stat_json(e, ctx, status, cross) for e in cited},
        "verification": {
            "stat_auditor": {"ok": all(s.audit["ok"] for s in published if s.audit), **totals},
            "fact_check_claims": fc_counts,
            "sections_published": sum(s.status == "published" for s in everything),
            "sections_withheld": sum(s.status == "withheld" for s in everything),
        },
        "methods": MODEL_DOCS,
    }
    return doc, state


def write(doc: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{doc['club']['slug']}.json"
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return path
