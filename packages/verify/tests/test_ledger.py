from datetime import UTC, datetime

import duckdb
import pytest
from dugout_verify.jsonpath import PathError, extract
from dugout_verify.ledger import EvidenceLedger, UnknownEvidence, render

T = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)
Q = {"kind": "http_json", "source": "fpl", "url": "https://x/api", "path": ["a"]}


@pytest.fixture
def ledger():
    return EvidenceLedger(duckdb.connect())


def test_record_is_deterministic_and_idempotent(ledger):
    kw = dict(
        entity_type="player",
        entity_id="rp1",
        metric="goals",
        value=7,
        source="fpl",
        source_tier=1,
        fetched_at=T,
        query=Q,
    )
    a, b = ledger.record(**kw), ledger.record(**kw)
    assert a == b and a.startswith("ev_")
    assert ledger.con.execute("SELECT count(*) FROM evidence_ledger").fetchone()[0] == 1
    ev = ledger.get(a)
    assert ev.value == 7.0 and ev.query == Q and ev.fetched_at == T


def test_query_must_be_rerunnable(ledger):
    with pytest.raises(ValueError):
        ledger.record(
            entity_type="p",
            entity_id="x",
            metric="m",
            value=1,
            source="s",
            source_tier=1,
            fetched_at=T,
            query={"url": "x"},
        )


def test_render_fills_placeholders_and_tracks_citations(ledger):
    g = ledger.record(
        entity_type="player",
        entity_id="rp1",
        metric="goals",
        value=7,
        source="fpl",
        source_tier=1,
        fetched_at=T,
        query=Q,
    )
    p = ledger.record(
        entity_type="player",
        entity_id="rp1",
        metric="chance",
        value=0.75,
        source="fpl",
        source_tier=1,
        fetched_at=T,
        query={**Q, "path": ["b"]},
    )
    text, cited = render(f"He has {{{{stat:{g}}}}} goals and a {{{{stat:{p}|pct}}}} chance.", ledger)
    assert text == "He has 7 goals and a 75% chance." and cited == [g, p]


def test_render_rejects_unknown_ids(ledger):
    with pytest.raises(UnknownEvidence):
        render("{{stat:ev_0000000000000000}}", ledger)


def test_jsonpath_extract():
    doc = {"elements": [{"id": 1, "g": 2}, {"id": 5, "g": 9, "team": {"id": 3}}]}
    assert extract(doc, ["elements", {"match": {"id": 5}}, "g"]) == 9
    assert extract(doc, ["elements", {"match": {"team.id": 3}}, "g"]) == 9
    assert extract(doc, ["elements", 0, "g"]) == 2
    with pytest.raises(PathError):
        extract(doc, ["elements", {"match": {"id": 99}}])
