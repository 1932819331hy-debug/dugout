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
from dugout_verify.ledger import PLACEHOLDER, EvidenceLedger, render

log = logging.getLogger(__name__)
CODE = re.compile(r"\[\s*(F\d+)(d|lo|hi)?\s*\]")  # [F3]; [F3d] a second slot; [F3lo]/[F3hi] a range

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
    example = f.template
    if f.eid:
        for slot, code in (("{p}", ""), ("{d}", "d"), ("{lo}", "lo"), ("{hi}", "hi")):
            example = example.replace(slot, f"[{f.key}{code}]")
    kind = f"code [{f.key}]" if f.eid else "statement"
    gloss = f"; reading: {f.gloss}" if f.gloss else ""
    return f"- [{f.key}] {f.subject} — {f.label} ({kind}{gloss}). Example: {example}"


def substitute(text: str, facts: list[Fact]) -> tuple[str, list[str]]:
    by_key = {f.key: f for f in facts}
    errors: list[str] = []

    def sub(m: re.Match[str]) -> str:
        key, suffix = m.group(1), m.group(2) or ""
        f = by_key.get(key)
        if f is None or (suffix == "d" and not f.when) or (suffix in ("lo", "hi") and not f.range):
            errors.append(f"unknown fact code [{key}{suffix}]")
            return m.group(0)
        if not f.eid:
            errors.append(f"[{f.key}] is a statement, not a value")
            return m.group(0)
        return f.slot(suffix)

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
    allowed_ids = {i for f in facts for i in f.ids()}
    for m in PLACEHOLDER.finditer(template):
        if m.group(1) not in allowed_ids:
            errors.append("placeholder not from the fact list")
    if MALFORMED.search(PLACEHOLDER.sub(" ", template)) or CODE.search(template):
        errors.append("malformed or unresolved fact code")
    stray = stray_numbers(template, allowed_names)
    if stray:
        errors.append(f"numbers written directly: {', '.join(sorted(set(stray)))}")
    if len(claims(template)) > max_sentences + 2:
        errors.append("too many sentences")
    if errors:  # cheap checks first; Fact-Check (NLI) only on drafts that pass them
        return errors
    # the same Fact-Check the publish gate runs: a draft whose sentences would be cut is rejected here
    report = checker.check(template, ledger, render=lambda t: render(t, ledger)[0])
    for c in report.claims:
        if c.status in ("conflicting", "unverified"):
            hint = (
                ""
                if c.type == "stat"
                else " (state it with a fact code, or in the wording of a statement fact)"
            )
            errors.append(f"sentence {c.index + 1} {c.status}: {c.reason}{hint}")
    # a note must actually answer: state facts, not only advise (a "check the club website" note passes every
    # check while saying nothing)
    stated = sum(1 for c in report.claims if c.status == "verified")
    if facts and stated < min(2, len(facts)):
        errors.append(
            "the note states too few of the facts; state the facts first, then at most one recommendation"
        )
    if sum(1 for c in report.claims if c.type == "analysis") > 1:
        errors.append("more than one recommendation sentence")
    return errors


_STOP = {
    "what",
    "which",
    "when",
    "where",
    "does",
    "have",
    "with",
    "this",
    "that",
    "their",
    "they",
    "will",
    "would",
    "should",
    "could",
    "about",
    "from",
    "most",
    "much",
    "many",
    "league",
    "season",
    "model",
}
_SYNONYMS = {
    "press": "defensive",
    "pressing": "defensive",
    "play": "style",
    "sold": "sale",
    "sell": "sale",
    "worth": "value",
    "expire": "contract",
    "expiring": "contract",
    "minutes": "minutes",
    "xg": "expected",
}


def relevance(f: Fact, question: str) -> int:
    """How well a fact answers the question: words shared with its subject/label (with a few synonyms)."""
    words = {w for w in re.findall(r"[a-z]+", question.lower()) if len(w) > 3 and w not in _STOP}
    words |= {_SYNONYMS[w] for w in words if w in _SYNONYMS}
    text = f"{f.subject} {f.label}".lower()
    return sum(1 for w in words if w in text)


def fallback(facts: list[Fact], limit: int, question: str = "") -> str:
    """Template sentences for the facts that best answer the question (tool order breaks ties)."""
    ranked = sorted(range(len(facts)), key=lambda i: (-relevance(facts[i], question), i))
    keep = sorted(ranked[:limit])  # keep tool order in the prose
    return " ".join(facts[i].sentence() for i in keep)


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
                return Draft(
                    text, f"llm:{getattr(llm, 'used', llm.name)}", attempts
                )  # the model that actually wrote it
            user += (
                f"\n\nYour previous note was rejected: {'; '.join(errors)}. Rewrite it following the rules; "
                "copy the example sentences if unsure."
            )
    return Draft(fallback(facts, template_limit, question), "template", attempts)
