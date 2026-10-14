from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dugout_pipeline.adapters.base import IngestContext
from dugout_pipeline.db import connect
from dugout_pipeline.ids import ReepMatch, StaticIndex
from dugout_pipeline.settings import Settings
from dugout_pipeline.testing import ReplayTransport

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)

# Reep Register excerpt for the 20 clubs (CC0), keyed by Opta team id as FPL reports it.
_REEP_CLUBS = json.loads((FIXTURES / "reep" / "clubs.json").read_text(encoding="utf-8"))


def sample(name: str) -> bytes:
    return gzip.decompress((FIXTURES / "samples" / name).read_bytes())


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        cache_dir=tmp_path / "cache",
        football_data_org_key="test-fdo",
        guardian_api_key="test-guardian",
        api_football_key="test-af",
    )


@pytest.fixture
def reep() -> StaticIndex:
    return StaticIndex(
        {
            ("opta", "team_numeric", code): ReepMatch(c["reep_id"], c["label"], c["ids"])
            for code, c in _REEP_CLUBS.items()
        }
    )


def make_ctx(settings, reep, *sources: str) -> IngestContext:
    return IngestContext(
        con=connect(),
        settings=settings,
        reep_index=reep,
        now=NOW,
        throttle=False,
        transport=ReplayTransport(*sources) if sources else None,
    )


@pytest.fixture
def ctx(settings, reep) -> IngestContext:
    return make_ctx(settings, reep, "fpl", "football_data_org", "guardian", "rss")


@pytest.fixture
def ctx_with_fpl(ctx) -> IngestContext:
    from dugout_pipeline.adapters.fpl import FPLAdapter

    a = FPLAdapter(ctx)
    a.ingest()
    a.close()
    return ctx
