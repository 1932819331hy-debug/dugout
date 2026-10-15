"""Evidence ledger: every number dugout may publish is a row here.

A ledger row stores the value, where it came from (source, URL, fetch time) and a *re-runnable query*
so the Stat Auditor can recompute it later. Agents cite rows as `{{stat:<id>}}`; `render()` fills them.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import duckdb

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS evidence_ledger (
    id           VARCHAR PRIMARY KEY,      -- ev_<16 hex>
    entity_type  VARCHAR NOT NULL,         -- player | club | manager | match | league
    entity_id    VARCHAR NOT NULL,         -- reep id where available, else dugout id
    metric       VARCHAR NOT NULL,         -- e.g. goals, minutes, chance_of_playing_next_round
    value_num    DOUBLE,
    value_text   VARCHAR,
    unit         VARCHAR,
    source       VARCHAR NOT NULL,         -- adapter name
    source_url   VARCHAR,                  -- redacted URL, never contains secrets
    source_tier  INTEGER NOT NULL,         -- 1 official .. 5 social
    fetched_at   TIMESTAMPTZ NOT NULL,
    query        JSON NOT NULL,            -- re-runnable spec, see LedgerQuery
    recorded_at  TIMESTAMPTZ NOT NULL
);
"""

PLACEHOLDER = re.compile(r"\{\{stat:(ev_[0-9a-f]{16})(?:\|([a-z0-9_.%]+))?\}\}")
# Display formats a placeholder may request: {{stat:id|pct}}, {{stat:id|eur_m}}, {{stat:id|.1f}}, {{stat:id|ord}}.
FORMATS = ("pct", "pct1", "eur_m", "int", "ord", "signed", "date", "score")
# sql: warehouse query; http_json: path into an archived API response; file_csv: cell of a committed CSV file.
QUERY_KINDS = ("sql", "http_json", "file_csv")


@dataclass(frozen=True)
class Evidence:
    id: str
    entity_type: str
    entity_id: str
    metric: str
    value_num: float | None
    value_text: str | None
    unit: str | None
    source: str
    source_url: str | None
    source_tier: int
    fetched_at: datetime
    query: dict[str, Any]

    @property
    def value(self) -> float | str | None:
        return self.value_num if self.value_num is not None else self.value_text


def evidence_id(
    entity_type: str, entity_id: str, metric: str, source: str, query: dict[str, Any], fetched_at: datetime
) -> str:
    blob = json.dumps(
        [entity_type, entity_id, metric, source, query, fetched_at.isoformat()], sort_keys=True, default=str
    )
    return "ev_" + hashlib.sha256(blob.encode()).hexdigest()[:16]


class EvidenceLedger:
    def __init__(self, con: duckdb.DuckDBPyConnection):
        self.con = con
        con.execute(LEDGER_DDL)

    def record(
        self,
        *,
        entity_type: str,
        entity_id: str,
        metric: str,
        value: float | int | str | None,
        source: str,
        source_tier: int,
        fetched_at: datetime,
        query: dict[str, Any],
        source_url: str | None = None,
        unit: str | None = None,
    ) -> str:
        if query.get("kind") not in QUERY_KINDS:
            raise ValueError(
                f"ledger query must declare a 'kind' ({' | '.join(QUERY_KINDS)}) so it can be re-run"
            )
        if query["kind"] == "sql" and "sql" not in query:
            raise ValueError("sql ledger query needs 'sql' (and optional 'params')")
        eid = evidence_id(entity_type, entity_id, metric, source, query, fetched_at)
        num = float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
        text = None if num is not None or value is None else str(value)
        self.con.execute(
            """INSERT INTO evidence_ledger VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT (id) DO NOTHING""",
            [
                eid,
                entity_type,
                entity_id,
                metric,
                num,
                text,
                unit,
                source,
                source_url,
                source_tier,
                fetched_at,
                json.dumps(query, sort_keys=True),
                datetime.now(UTC),
            ],
        )
        return eid

    def record_sql(
        self,
        sql: str,
        params: list[Any] | None = None,
        *,
        entity_type: str,
        entity_id: str,
        metric: str,
        source: str,
        source_tier: int,
        fetched_at: datetime,
        source_url: str | None = None,
        unit: str | None = None,
    ) -> tuple[str, float | str | None]:
        """Runs a single-value warehouse query and records its result with the query itself, so the Stat
        Auditor can re-run it. Returns (ledger id, value)."""
        query = {"kind": "sql", "sql": " ".join(sql.split()), "params": list(params or [])}
        value = run_sql(self.con, query)
        eid = self.record(
            entity_type=entity_type,
            entity_id=entity_id,
            metric=metric,
            value=value,
            source=source,
            source_tier=source_tier,
            fetched_at=fetched_at,
            query=query,
            source_url=source_url,
            unit=unit,
        )
        return eid, value

    def get(self, eid: str) -> Evidence | None:
        row = self.con.execute(
            "SELECT id, entity_type, entity_id, metric, value_num, value_text, unit, source, source_url, "
            "source_tier, fetched_at, query FROM evidence_ledger WHERE id = ?",
            [eid],
        ).fetchone()
        if row is None:
            return None
        *head, q = row
        return Evidence(*head, query=json.loads(q))


class UnknownEvidence(KeyError):
    pass


def run_sql(con: duckdb.DuckDBPyConnection, query: dict[str, Any]) -> float | str | None:
    """Executes a recorded `sql` query: it must return exactly one row with one column."""
    rows = con.execute(query["sql"], query.get("params") or []).fetchall()
    if len(rows) != 1 or len(rows[0]) != 1:
        raise ValueError(f"ledger sql must return one value, got {len(rows)} rows")
    v = rows[0][0]
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, int | float):
        return float(v)
    if hasattr(v, "isoformat"):  # dates
        return v.isoformat()
    return float(v)  # Decimal


def format_value(ev: Evidence, fmt: str | None) -> str:
    v = ev.value
    if v is None:
        return "n/a"
    if isinstance(v, str):
        if fmt == "date":
            try:
                d = datetime.fromisoformat(v)
            except ValueError:
                return v
            return f"{d.day} {d:%B %Y}"
        return v
    if fmt == "score":
        return f"{v:.0f}/100"
    if fmt == "pct":
        return f"{v * 100:.0f}%"
    if fmt == "pct1":
        return f"{v * 100:.1f}%"
    if fmt == "eur_m":
        return f"€{v / 1e6:.1f}m" if abs(v) < 1e8 else f"€{v / 1e6:.0f}m"
    if fmt == "int":
        return str(round(v))
    if fmt == "signed":
        return f"{v:+.0f}" if float(v).is_integer() else f"{v:+.2f}"
    if fmt == "ord":
        n = round(v)
        suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"
    if fmt and fmt.startswith(".") and fmt.endswith("f"):
        return format(v, fmt)
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}"


def render(text: str, ledger: EvidenceLedger) -> tuple[str, list[str]]:
    """Fill `{{stat:id}}` / `{{stat:id|fmt}}` placeholders. Returns (text, cited ids). Unknown ids raise."""
    cited: list[str] = []

    def sub(m: re.Match[str]) -> str:
        ev = ledger.get(m.group(1))
        if ev is None:
            raise UnknownEvidence(m.group(1))
        cited.append(ev.id)
        return format_value(ev, m.group(2))

    return PLACEHOLDER.sub(sub, text), cited
