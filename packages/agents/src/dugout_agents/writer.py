"""Turns fact cards into prose.

The LLM writes with fact *codes* ([F3]); code swaps each code for its `{{stat:id}}` placeholder, so a small model
never has to copy a hash correctly. A draft is accepted only if it passes the Stat Auditor's static checks
(no stray numbers, no unknown placeholders) and the Fact-Check binding rule (each cited number sits in a sentence
that names its subject and describes its metric). One retry with the errors; then the deterministic template.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from dugout_agents.facts import Fact
from dugout_agents.llm import LLM, LLMError
from dugout_verify.auditor import MALFORMED, stray_numbers
from dugout_verify.claims import claims
from dugout_verify.factcheck import FactChecker
from dugout_verify.ledger import PLACEHOLDER, EvidenceLedger

log = logging.getLogger(__name__)
CODE = re.compile(r"\[\s*(F\d+)\s*\]")

SYSTEM = """You are the {role} in the sporting department of {club}. You write short briefing notes for the \
sporting director.
Hard rules:
1. Never write a digit or a number word. A number appears ONLY as a fact code such as [F3]; the code is replaced \
by the real value later. Put the code exactly where the value belongs.
2. Use only the facts listed. Add nothing from your own knowledge: no other players, results, injuries, transfers \
or dates.
3. A sentence that uses a fact code must name the player, club or match it is about and say what the number \
measures, like the example given with each fact.
4. Facts marked "statement" have no code: you may restate them in your own words, without changing their meaning.
5. At most one sentence may give a recommendation; start it with "We recommend" or use "should".
6. Write {n} sentences of plain text. No lists, no headings, no preamble."""

USER = """Question: {question}

Facts:
{cards}

Write the note now."""


@dataclass
class Draft:
    template: str
    writer: str  # "llm:<model>" or "template"
    attempts: list[dict] = field(default_factory=list)


def card(f: Fact) -> str:
    example = f.template.replace("{p}", f"[{f.key}]") if f.eid else f.template
    kind = f"code [{f.key}]" if f.eid else "statement"
    gloss = f"; reading: {f.gloss}" if f.gloss else ""
    return f"- [{f.key}] {f.subject} — {f.label} ({kind}{gloss}). Example: {example}"


def substitute(text: str, facts: list[Fact]) -> tuple[str, list[str]]:
    by_key = {f.key: f for f in facts}
    errors: list[str] = []

    def sub(m: re.Match[str]) -> str:
        f = by_key.get(m.group(1))
        if f is None:
            errors.append(f"unknown fact code [{m.group(1)}]")
            return m.group(0)
        if not f.eid:
            errors.append(f"[{f.key}] is a statement, not a value")
            return m.group(0)
        return f.placeholder

    out = CODE.sub(sub, text.strip())
    out = re.sub(r"\s+", " ", out).strip()
    return out, errors


def validate(
    template: str,
    facts: list[Fact],
    ledger: EvidenceLedger,
    checker: FactChecker,
    allowed_names: list[str],
    max_sentences: int,
) -> list[str]:
    errors = []
    allowed_ids = {f.eid for f in facts if f.eid}
    for m in PLACEHOLDER.finditer(template):
        if m.group(1) not in allowed_ids:
            errors.append("placeholder not from the fact list")
    if MALFORMED.search(PLACEHOLDER.sub(" ", template)) or CODE.search(template):
        errors.append("malformed or unresolved fact code")
    stray = stray_numbers(template, allowed_names)
    if stray:
        errors.append(f"numbers written directly: {', '.join(sorted(set(stray)))}")
    cl = claims(template)
    if len(cl) > max_sentences + 2:
        errors.append("too many sentences")
    for k, c in enumerate(cl):
        if c.type == "stat":
            r = checker.check_binding(c, cl[k - 1].text if k else "", ledger)
            if r.status != "verified":
                errors.append(f"sentence {k + 1}: {r.reason}")
    return errors


def fallback(facts: list[Fact], limit: int) -> str:
    return " ".join(f.sentence() for f in facts[:limit])


def write(
    llm: LLM | None,
    *,
    role: str,
    club: str,
    question: str,
    facts: list[Fact],
    ledger: EvidenceLedger,
    checker: FactChecker,
    allowed_names: list[str],
    sentences: int = 4,
    template_limit: int = 8,
) -> Draft:
    if not facts:
        return Draft("", "template")
    attempts: list[dict] = []
    if llm is not None:
        system = SYSTEM.format(role=role, club=club, n=sentences)
        user = USER.format(question=question, cards="\n".join(card(f) for f in facts))
        for _ in range(2):
            try:
                raw = llm.complete(system, user)
            except LLMError as exc:
                attempts.append({"error": str(exc)})
                break
            text, errors = substitute(raw, facts)
            errors += validate(text, facts, ledger, checker, allowed_names, sentences)
            attempts.append({"errors": errors})
            if not errors:
                return Draft(text, f"llm:{llm.name}", attempts)
            user += (
                f"\n\nYour previous note was rejected: {'; '.join(errors)}. Rewrite it following the rules; "
                "copy the example sentences if unsure."
            )
    return Draft(fallback(facts, template_limit), "template", attempts)
