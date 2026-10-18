"""Regression coverage for the offline kickoff and API quota guard."""

import json
from datetime import UTC, datetime, timedelta

from scripts.kickoff_lineups_due import budget_allows, due_clubs

NOW = datetime(2026, 10, 19, 14, tzinfo=UTC)


def row(match: str, kickoff: datetime, as_of: datetime = NOW) -> dict[str, str]:
    return {"match_id": match, "kickoff_utc": kickoff.isoformat(), "as_of": as_of.isoformat()}


def test_filter_deduplicate_and_schedule_window():
    match = "premier_league:2026-27:arsenal:chelsea"
    rows = [
        row(match, NOW + timedelta(minutes=45)),
        row(match, NOW + timedelta(minutes=45)),
        row("premier_league:2026-27:everton:fulham", NOW + timedelta(minutes=61)),
        row("premier_league:2026-27:leeds-united:liverpool", NOW),
        row("serie_a:2026-27:internazionale:milan", NOW + timedelta(minutes=30)),
    ]
    assert due_clubs(rows, NOW) == ["arsenal", "chelsea"]


def test_newer_kickoff_supersedes_stale_forecast_regardless_of_order():
    match = "premier_league:2026-27:arsenal:liverpool"
    rows = [
        row(match, NOW + timedelta(minutes=30), NOW - timedelta(days=1)),
        row(match, NOW + timedelta(days=2), NOW - timedelta(hours=1)),
    ]
    assert due_clubs(rows, NOW) == []
    assert due_clubs(list(reversed(rows)), NOW) == []


def test_bad_ids_and_naive_timestamps_are_ignored():
    rows = [
        row("premier_league:2026-27:arsenal:bad;echo", NOW + timedelta(minutes=40)),
        row("premier_league:2026-27:arsenal", NOW + timedelta(minutes=40)),
        row("premier_league:2026-27:arsenal:chelsea", NOW.replace(tzinfo=None)),
    ]
    assert due_clubs(rows, NOW) == []


def test_allowance_reserves_calls_for_regular_jobs(tmp_path):
    path = tmp_path / "api_football.json"
    assert budget_allows(path, NOW, 2)
    path.write_text(json.dumps({NOW.date().isoformat(): 75}))
    assert budget_allows(path, NOW, 2)
    path.write_text(json.dumps({NOW.date().isoformat(): 76}))
    assert not budget_allows(path, NOW, 2)


def test_corrupt_or_impossible_allowance_fails_closed(tmp_path):
    path = tmp_path / "api_football.json"
    path.write_text("{broken")
    assert not budget_allows(path, NOW)
    for n in (-1, True, "five"):
        path.write_text(json.dumps({NOW.date().isoformat(): n}))
        assert not budget_allows(path, NOW)
