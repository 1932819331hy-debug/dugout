"""API-Football injury history for leagues without FPL: budget reserve, resume from cache, Transfermarkt ids."""

from __future__ import annotations

import json

import pandas as pd
import pytest
from conftest import make_ctx
from dugout_pipeline.adapters import api_football as af
from dugout_pipeline.ids import ReepMatch, StaticIndex
from dugout_pipeline.matching import squad_player


@pytest.fixture
def la_liga(settings, tmp_path, monkeypatch):
    """Recorded La Liga lists (hand-trimmed from the cache: six absentees a season), a Reep bridge for Marcão and
    a two-player Osasuna squad in a miniature transfermarkt-datasets."""
    monkeypatch.setattr(af, "INJURY_DIR", tmp_path / "injuries")
    tm = tmp_path / "tm"
    tm.mkdir()
    monkeypatch.setattr(af, "TM_DIR", tm)
    pd.DataFrame(
        {
            "player_id": [9001, 9002, 9003],
            "player_club_id": [331, 331, 368],
            "date": ["2022-09-01", "2022-09-01", "2022-09-01"],
            "competition_id": ["ES1", "ES1", "ES1"],
        }
    ).to_parquet(tm / "appearances.parquet")
    pd.DataFrame(
        {"player_id": [9001, 9002, 9003], "name": ["Rubén García", "Kike Saverio", "Isco"]}
    ).to_parquet(tm / "players.parquet")
    pd.DataFrame({"club_id": [331, 368], "name": ["CA Osasuna", "Sevilla FC"]}).to_parquet(
        tm / "clubs.parquet"
    )
    reep = StaticIndex(
        {
            ("api_football", "player", "433"): ReepMatch(
                "rp-marcao", "Marcão", {"transfermarkt/spieler": "5555"}
            )
        }
    )
    ctx = make_ctx(settings, reep, "api_football_history")
    ctx.league = "la_liga"
    return ctx


def test_backfill_maps_absentees_and_resumes_from_the_cache(la_liga):
    a = af.ApiFootballHistoryAdapter(la_liga)
    counts = a.ingest()
    assert counts == {
        "injury_history_rows": 18,
        "injury_rows_matched": 5,
        "api_calls": 3,
        "seasons_pending": 0,
    }
    df = pd.read_parquet(af.injury_file("la_liga", 2022))
    by = df.drop_duplicates("player_name").set_index("player_name")
    assert (by.loc["Marcao", "tm_player_id"], by.loc["Marcao", "match"]) == ("5555", "reep")
    assert (by.loc["R. Garcia", "tm_player_id"], by.loc["R. Garcia", "match"]) == ("9001", "name_in_club")
    assert by.loc["Kike Saverio", "tm_player_id"] == "9002" and by.loc["Isco", "tm_player_id"] == "9003"
    assert pd.isna(by.loc["Munir El Haddadi", "tm_player_id"])  # not in the squad: no guess
    assert set(df.league) == {"la_liga"}
    # a second run takes every season from the cache
    assert a.ingest()["api_calls"] == 0
    a.close()


def test_backfill_stops_before_the_reserve(la_liga):
    a = af.ApiFootballHistoryAdapter(la_liga)
    used = a.daily_limit - af.HISTORY_RESERVE  # what the nightly still needs is all that is left
    a.client.budget.path.parent.mkdir(parents=True, exist_ok=True)
    a.client.budget.path.write_text(json.dumps({la_liga.now.date().isoformat(): used}))
    a.client.budget._today = la_liga.now.date
    counts = a.ingest()
    assert counts["seasons_pending"] == 3 and counts["api_calls"] == 0
    assert all("injuries" not in u for u in la_liga.transport.requests)
    assert not af.injury_file("la_liga", 2022).exists()
    a.close()


def test_status_raises_the_local_count(la_liga):
    a = af.ApiFootballHistoryAdapter(la_liga)
    a.client.budget._today = la_liga.now.date
    a.sync_budget()  # the recorded status reports 11 requests used today
    assert a.client.budget.used() == 11
    a.close()


def test_squad_player_refuses_to_guess():
    squad = [("1", "Rubén García"), ("2", "Rubén Peña"), ("3", "Kike García")]
    assert squad_player("R. Pena", squad) == "2"
    assert squad_player("Garcia", squad) is None  # two Garcías
    assert squad_player("Kike Garcia", squad) == "3"
    assert squad_player("Totally Different", squad) is None
