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
        if "kind" not in query:
            raise ValueError("ledger query must declare a 'kind' (sql | http_json) so it can be re-run")
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


def format_value(ev: Evidence, fmt: str | None) -> str:
    v = ev.value
    if v is None:
        return "n/a"
    if isinstance(v, str):
        return v
    if fmt == "pct":
        return f"{v * 100:.0f}%"
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
