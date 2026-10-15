"""Stat Auditor: deterministic checks on a draft before anything is published. No LLM anywhere in here.

1. Placeholders: every `{{stat:id}}` must resolve to a ledger row.
2. Stray numbers: once placeholders (and allow-listed proper names) are masked, no digit and no number word may
   remain. A number the LLM typed itself is untraceable by definition.
3. Re-run: every cited row's query is executed again (`sql` against the warehouse, `http_json` against the
   archived response) and must reproduce the stored value within tolerance.
4. Cross-source: goals, minutes, injuries and fees are compared with an independent source where we hold one.

Each cited stat gets a status for the website: `verified` (re-ran, and a second source agrees),
`single_source` (re-ran; no second source exists), `model_output` (re-ran; produced by a dugout model).
"""

from __future__ import annotations

import csv
import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from dugout_verify.jsonpath import PathError, extract
from dugout_verify.ledger import PLACEHOLDER, Evidence, EvidenceLedger, run_sql

# Resolves an http_json query to the archived JSON document it was extracted from (None = not available).
BodyResolver = Callable[[dict[str, Any]], Any]

NUMBER_WORDS = (  # noqa: SIM905 - one readable string
    "two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million billion "
    "dozen half-dozen twice thrice"
).split()
# "one" is left out on purpose ("one of the best", "no one"); ordinals too ("second half", "first team").
STRAY = re.compile(r"\d|\b(" + "|".join(NUMBER_WORDS) + r")\b|[½¼¾⅓⅔]", re.IGNORECASE)
# Placeholder-looking leftovers once valid placeholders are removed (typos, invented ids, other tags).
MALFORMED = re.compile(r"\{\{[^}]*\}\}|\{\{|\}\}|stat:ev_\w*")

REL_TOL, ABS_TOL = 0.005, 1e-6


@dataclass
class Finding:
    check: str  # placeholder | stray_number | rerun | cross_source
    severity: str  # error | warning
    message: str
    evidence_id: str | None = None


@dataclass
class AuditReport:
    findings: list[Finding] = field(default_factory=list)
    stat_status: dict[str, str] = field(default_factory=dict)
    cross_checks: dict[str, list[dict]] = field(default_factory=dict)
    numbers_total: int = 0
    numbers_untraceable: int = 0

    @property
    def ok(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "numbers_total": self.numbers_total,
            "numbers_untraceable": self.numbers_untraceable,
            "stat_status": self.stat_status,
            "cross_checks": self.cross_checks,
            "findings": [f.__dict__ for f in self.findings],
        }


def mask_names(text: str, names: Iterable[str]) -> str:
    """Blanks allow-listed proper names (e.g. "Mainz 05") so their digits are not counted as numbers."""
    for n in sorted({n for n in names if n and any(c.isdigit() for c in n)}, key=len, reverse=True):
        text = text.replace(n, " " * len(n))
    return text


def stray_numbers(template: str, allowed_names: Iterable[str] = ()) -> list[str]:
    bare = PLACEHOLDER.sub(" ", template)
    bare = mask_names(bare, allowed_names)
    return [m.group(0) for m in STRAY.finditer(bare)]


def same_value(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, int | float) and isinstance(b, int | float):
        if math.isnan(a) or math.isnan(b):
            return math.isnan(a) and math.isnan(b)
        return abs(a - b) <= max(ABS_TOL, REL_TOL * abs(b))
    return str(a) == str(b)


def rerun(
    ev: Evidence,
    con: duckdb.DuckDBPyConnection,
    resolve_body: BodyResolver | None,
    files_root: Path | None = None,
) -> Any:
    q = ev.query
    if q["kind"] == "sql":
        return run_sql(con, q)
    if q["kind"] == "file_csv":
        path = (files_root or Path.cwd()) / q["path"]
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if all(row.get(k) == str(v) for k, v in q["key"].items()):
                    cell = row[q["column"]]
                    try:
                        return float(cell) if ev.value_num is not None else cell
                    except ValueError:
                        return cell
        raise LookupError(f"no row {q['key']} in {q['path']}")
    if q["kind"] == "http_json":
        if resolve_body is None:
            raise LookupError("no archived-response resolver configured")
        doc = resolve_body(q)
        if doc is None:
            raise LookupError(f"archived response not available for {q.get('url')}")
        v = extract(doc, q["path"])
        if isinstance(v, bool):
            return float(v)
        if isinstance(v, int | float):
            return float(v)
        if isinstance(v, str):
            try:  # FPL serialises some numbers as strings ("4.3")
                return float(v) if ev.value_num is not None else v
            except ValueError:
                return v
        return v
    raise ValueError(f"unknown query kind {q['kind']!r}")


# ---- cross-source checks -------------------------------------------------------------------------------
# Each returns a list of {"source", "value", "agrees"} for other sources, or [] when none exists.
CrossCheck = Callable[[duckdb.DuckDBPyConnection, Evidence], list[dict]]


def _match_goals(con: duckdb.DuckDBPyConnection, ev: Evidence) -> list[dict]:
    col = "home_goals" if ev.metric.endswith("home_goals") else "away_goals"
    rows = con.execute(
        f"SELECT source, {col} FROM match_observations WHERE match_id = ? AND source <> ? AND {col} IS NOT NULL",
        [ev.entity_id, ev.source],
    ).fetchall()
    return [{"source": s, "value": v, "agrees": same_value(float(v), ev.value_num)} for s, v in rows]


def _season_sum(column: str, lag_tolerance: float) -> CrossCheck:
    """FPL season totals (bootstrap) vs the sum of per-match rows (element-summary / API-Football)."""

    def check(con: duckdb.DuckDBPyConnection, ev: Evidence) -> list[dict]:
        if ev.entity_type != "player" or ev.value_num is None:
            return []
        season = (ev.query.get("season") if isinstance(ev.query, dict) else None) or _current_season(con)
        rows = con.execute(
            f"""SELECT s.source, sum(s.{column}) FROM player_match_stats s JOIN matches m USING (match_id)
                WHERE s.player_id = ? AND m.season = ? AND s.{column} IS NOT NULL GROUP BY 1""",
            [ev.entity_id, season],
        ).fetchall()
        out = []
        for src, v in rows:
            if v is None:
                continue
            agrees = abs(float(v) - ev.value_num) <= lag_tolerance
            out.append({"source": f"{src} (per-match sum)", "value": float(v), "agrees": agrees})
        return out

    return check


def _injury_status(con: duckdb.DuckDBPyConnection, ev: Evidence) -> list[dict]:
    """FPL chance of playing vs API-Football's missing-fixture list on the same day (when the window covers it)."""
    if ev.entity_type != "player":
        return []
    rows = con.execute(
        """SELECT source, status FROM injuries WHERE player_id = ? AND source <> ? AND snapshot_date = (
               SELECT max(snapshot_date) FROM injuries WHERE player_id = ? AND source <> ?)""",
        [ev.entity_id, ev.source, ev.entity_id, ev.source],
    ).fetchall()
    out = []
    for src, status in rows:
        out_flag = status in ("injured", "suspended", "unavailable")
        # API-Football lists only players out; "doubtful" (50-75%) is not a disagreement either way
        agrees = (ev.value_num is None) or (ev.value_num <= 0.25 if out_flag else ev.value_num >= 0.5)
        out.append({"source": src, "value": status, "agrees": agrees})
    return out


def _fee(con: duckdb.DuckDBPyConnection, ev: Evidence) -> list[dict]:
    if ev.entity_type != "player" or ev.value_num is None:
        return []
    rows = con.execute(
        """SELECT source, fee_eur FROM transfers WHERE player_id = ? AND source <> ? AND fee_eur > 0
           ORDER BY date DESC LIMIT 3""",
        [ev.entity_id, ev.source],
    ).fetchall()
    return [
        {"source": s, "value": v, "agrees": abs(v - ev.value_num) <= 0.15 * max(v, ev.value_num)}
        for s, v in rows
    ]


def _current_season(con: duckdb.DuckDBPyConnection) -> str | None:
    row = con.execute("SELECT max(season) FROM matches").fetchone()
    return row[0] if row else None


CROSS_CHECKS: dict[str, tuple[CrossCheck, str]] = {
    # metric -> (check, severity when sources disagree)
    "home_goals": (_match_goals, "error"),
    "away_goals": (_match_goals, "error"),
    "season_goals_scored": (_season_sum("goals", 0), "error"),
    "season_assists": (_season_sum("assists", 0), "warning"),  # assist definitions differ between providers
    "season_minutes": (_season_sum("minutes", 90), "error"),  # per-match feed may lag one gameweek
    "season_chance_of_playing_next_round": (_injury_status, "warning"),
    "chance_of_playing": (_injury_status, "warning"),
    "transfer_fee": (_fee, "warning"),
}


def audit(
    template: str,
    ledger: EvidenceLedger,
    con: duckdb.DuckDBPyConnection | None = None,
    *,
    resolve_body: BodyResolver | None = None,
    allowed_names: Iterable[str] = (),
    cross_checks: dict[str, tuple[CrossCheck, str]] | None = None,
    files_root: Path | None = None,
) -> AuditReport:
    """Audits a draft *template* (text with `{{stat:id}}` placeholders, before rendering)."""
    con = con or ledger.con
    checks = CROSS_CHECKS if cross_checks is None else cross_checks
    rep = AuditReport()

    for m in MALFORMED.finditer(PLACEHOLDER.sub(" ", template)):
        rep.findings.append(Finding("placeholder", "error", f"malformed placeholder {m.group(0)!r}"))

    stray = stray_numbers(template, allowed_names)
    ids = [m.group(1) for m in PLACEHOLDER.finditer(template)]
    rep.numbers_total = len(ids) + len(stray)
    rep.numbers_untraceable = len(stray)
    for s in stray:
        rep.findings.append(Finding("stray_number", "error", f"number not from the ledger: {s!r}"))

    for eid in dict.fromkeys(ids):
        ev = ledger.get(eid)
        if ev is None:
            rep.findings.append(Finding("placeholder", "error", "unknown ledger id", eid))
            rep.numbers_untraceable += 1
            continue
        try:
            fresh = rerun(ev, con, resolve_body, files_root)
        except (LookupError, PathError, ValueError, duckdb.Error) as exc:
            rep.findings.append(Finding("rerun", "error", f"could not re-run query: {exc}", eid))
            continue
        if not same_value(fresh, ev.value):
            rep.findings.append(
                Finding("rerun", "error", f"re-run gives {fresh!r}, ledger has {ev.value!r}", eid)
            )
            continue
        status = "model_output" if ev.source.startswith("dugout_model") else "single_source"
        if ev.metric in checks:
            fn, severity = checks[ev.metric]
            others = fn(con, ev)
            if others:
                rep.cross_checks[eid] = others
                if all(o["agrees"] for o in others):
                    status = "verified"
                else:
                    bad = ", ".join(f"{o['source']}={o['value']}" for o in others if not o["agrees"])
                    rep.findings.append(
                        Finding("cross_source", severity, f"{ev.metric}: {ev.value} vs {bad}", eid)
                    )
                    status = "conflicting" if severity == "error" else "disputed"
        elif ev.source_tier == 1 and status == "single_source":
            status = "verified" if ev.query.get("kind") == "http_json" else status  # official API, re-read
        rep.stat_status[eid] = status
    return rep
