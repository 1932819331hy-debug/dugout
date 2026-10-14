"""Adapters other than FPL, on recorded/trimmed fixtures."""

import json
from datetime import UTC, date, datetime

import pytest
from conftest import NOW, make_ctx, sample
from dugout_pipeline.adapters.api_football import ApiFootballAdapter
from dugout_pipeline.adapters.base import SourceDisabled
from dugout_pipeline.adapters.clubelo import ClubEloAdapter
from dugout_pipeline.adapters.football_data_couk import FootballDataCoUkAdapter, season_code
from dugout_pipeline.adapters.football_data_org import FootballDataOrgAdapter
from dugout_pipeline.adapters.news import GuardianAdapter, RSSAdapter, tag_clubs
from dugout_pipeline.adapters.transfermarkt import (
    TransfermarktFileAdapter,
    TransfermarktRefresher,
    parse_money,
    parse_squad,
    write_squads_csv,
)
from dugout_pipeline.adapters.weather import UK_POSTCODE, OpenMeteoAdapter
from dugout_pipeline.adapters.wikidata import WikidataAdapter, parse_point
from dugout_pipeline.clubs import ClubResolver


def _run(adapter_cls, ctx, **kw):
    a = adapter_cls(ctx)
    try:
        return a.ingest(**kw)
    finally:
        a.close()


def test_football_data_org_cross_source(ctx_with_fpl):
    counts = _run(FootballDataOrgAdapter, ctx_with_fpl)
    con = ctx_with_fpl.con
    assert counts["standings"] == 20
    # observations use the shared match-id scheme over known club slugs, so they join with FPL's matches
    clubs = {r[0] for r in con.execute("SELECT club_id FROM clubs").fetchall()}
    mids = [
        r[0]
        for r in con.execute(
            "SELECT match_id FROM match_observations WHERE source='football_data_org'"
        ).fetchall()
    ]
    assert mids
    for mid in mids:
        league, season, home, away = mid.split(":")
        assert (league, season) == ("premier_league", "2026-27") and {home, away} <= clubs
    assert con.execute("SELECT count(*) FROM managers WHERE source='football_data_org'").fetchone()[0] > 0
    pts = con.execute("SELECT count(*) FROM evidence_ledger WHERE metric='league_points'").fetchone()[0]
    assert pts == 20


def test_guardian_and_rss(ctx_with_fpl):
    assert _run(GuardianAdapter, ctx_with_fpl)["news_items"] > 0
    assert _run(RSSAdapter, ctx_with_fpl)["news_items"] > 0
    con = ctx_with_fpl.con
    assert con.execute("SELECT count(*) FROM news_items WHERE url LIKE '%api-key%'").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM news_items WHERE len(club_ids) > 0").fetchone()[0] > 0


def test_tag_clubs_whole_words():
    names = {"liverpool": "liverpool", "arsenal": "arsenal", "everton": "everton"}
    assert tag_clubs("Liverpool beat Arsenal at Anfield", names) == ["arsenal", "liverpool"]
    assert tag_clubs("Evertonian fans", names) == []


def test_api_football_parsers(ctx_with_fpl):
    a = ApiFootballAdapter(ctx_with_fpl)
    try:
        fx = json.loads(sample("api_football_fixtures_2024.json"))["response"]
        a.resolver = ClubResolver(
            aliases=ctx_with_fpl.clubs.aliases, by_provider=dict(ctx_with_fpl.clubs.by_provider)
        )
        obs = a.parse_fixtures(fx, NOW)
        assert obs and all(o["match_id"].startswith("premier_league:2024-25:") for o in obs)
        liv_home = next(f for f in fx if f["teams"]["home"]["id"] == 40)
        mid = a._match_id(liv_home)
        xg = a.parse_xg(mid, liv_home, json.loads(sample("api_football_statistics.json")), NOW)[0]
        assert xg["home_xg"] == pytest.approx(2.65)
        lineup = a.parse_lineups(mid, json.loads(sample("api_football_lineups.json")), NOW)
        assert sum(r["starter"] for r in lineup) == 22
        inj = a.parse_injuries(json.loads(sample("api_football_injuries.json"))["response"], NOW)
        assert all(r["source"] == "api_football" for r in inj)
    finally:
        a.close()


def test_api_football_surfaces_plan_errors(ctx_with_fpl, monkeypatch):
    a = ApiFootballAdapter(ctx_with_fpl)

    class R:
        from_cache = False

        def json(self):
            return {"errors": {"plan": "Free plans do not have access to this season"}, "response": []}

    monkeypatch.setattr(a.client, "get", lambda *args, **kw: R())
    with pytest.raises(RuntimeError, match="Free plans"):
        a.call("fixtures", {"league": 39, "season": 2026})
    a.close()


def test_football_data_couk_parse(ctx):
    a = FootballDataCoUkAdapter(ctx)
    rows = a.parse(sample("football_data_couk_E0_2526.csv"), "2025-26", ClubResolver.from_config())
    a.close()
    assert season_code("2025-26") == "2526"
    first = rows[0]
    assert first["home"] == "liverpool" and first["away"] == "bournemouth"
    assert first["date"] == date(2025, 8, 15) and (first["home_goals"], first["away_goals"]) == (4, 2)
    assert first["odds_source"] and first["odds_home"] > 1


def test_clubelo_parse_maps_by_reep_name(ctx_with_fpl):
    # format documented at clubelo.com/API: Rank,Club,Country,Level,Elo,From,To
    text = "Rank,Club,Country,Level,Elo,From,To\n1,Liverpool,ENG,1,2010.5,2026-10-10,2026-10-17\n2,Barcelona,ESP,1,1990,2026-10-10,2026-10-17\n"
    a = ClubEloAdapter(ctx_with_fpl)
    rows = a.parse(text, date(2026, 10, 15), NOW)
    a.close()
    assert [(r["club_id"], r["elo"]) for r in rows] == [("liverpool", 2010.5)]


def test_wikidata_parse(ctx):
    doc = {
        "results": {
            "bindings": [
                {
                    "tm": {"value": "31"},
                    "venueLabel": {"value": "Anfield"},
                    "coord": {"value": "Point(-2.96083 53.4308)"},
                    "coach": {"value": "http://www.wikidata.org/entity/Q1"},
                    "coachLabel": {"value": "A Coach"},
                    "start": {"value": "2024-06-01T00:00:00Z"},
                    "dob": {"value": "1978-09-17T00:00:00Z"},
                },
            ]
        }
    }
    a = WikidataAdapter(ctx)
    venues, managers = a.parse(doc, {"31": "liverpool"}, NOW)
    a.close()
    assert venues["liverpool"] == ("Anfield", 53.4308, -2.96083)
    assert managers[0]["start_date"] == date(2024, 6, 1)
    assert parse_point("Point(1 2)") == (2.0, 1.0)


def test_open_meteo_parse_and_postcode(ctx):
    a = OpenMeteoAdapter(ctx)
    doc = json.loads(sample("open_meteo_forecast.json"))
    ko = datetime.fromisoformat(doc["hourly"]["time"][15]).replace(tzinfo=UTC)
    row = a.parse("m1", ko, doc, NOW)
    a.close()
    assert row and row["temp_c"] == doc["hourly"]["temperature_2m"][15]
    m = UK_POSTCODE.search("ANFIELD ROAD LIVERPOOL L4 0TH")
    assert m and m.group(1) + m.group(2) == "L40TH"


def test_transfermarkt_parsing():
    rows = parse_squad(sample("transfermarkt_kader_31.html"))
    assert len(rows) == 3
    assert all(r["tm_player_id"].isdigit() and r["market_value_eur"] for r in rows)
    assert (
        parse_money("€28.00m") == 28_000_000 and parse_money("€800k") == 800_000 and parse_money("-") is None
    )


def test_transfermarkt_refresher_refuses_in_ci(settings, reep):
    ctx = make_ctx(settings.model_copy(update={"ci": True}), reep)
    with pytest.raises(SourceDisabled):
        TransfermarktRefresher(ctx)


def test_transfermarkt_file_adapter_reads_committed_csv(ctx, tmp_path):
    path = tmp_path / "squads.csv"
    write_squads_csv(
        [
            {
                "tm_player_id": "1",
                "player_id": "rp1",
                "name": "A",
                "tm_club_id": "31",
                "club_id": "liverpool",
                "contract_expires": date(2028, 6, 30),
                "market_value_eur": 5e6,
                "season": "2026-27",
                "scraped_on": date(2026, 10, 10),
                "source_url": "https://www.transfermarkt.com/x",
            }
        ],
        path,
    )
    out = TransfermarktFileAdapter(ctx).ingest(path=path)
    assert out == {"market_values": 1, "contracts": 1, "evidence_ledger": 1}
