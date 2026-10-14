import pytest
from dugout_pipeline.clubs import ClubResolver, normalise, slugify


@pytest.mark.parametrize(
    "name,slug",
    [
        ("Liverpool FC", "liverpool"),
        ("Brighton & Hove Albion", "brighton-hove-albion"),
        ("AFC Bournemouth", "bournemouth"),
        ("Tottenham Hotspur", "tottenham-hotspur"),
    ],
)
def test_slugify(name, slug):
    assert slugify(name) == slug


def test_normalise_strips_accents_and_suffixes():
    assert normalise("Nott'm Forest") == "nott m forest"
    assert normalise("Atlético Madrid") == "atletico madrid"


@pytest.mark.parametrize(
    "raw,slug",
    [
        ("Man Utd", "manchester-united"),
        ("Manchester United FC", "manchester-united"),
        ("Spurs", "tottenham-hotspur"),
        ("Nott'm Forest", "nottingham-forest"),
        ("Nottingham Forest FC", "nottingham-forest"),
        ("Brighton & Hove Albion FC", "brighton-hove-albion"),
        ("Bournemouth", "bournemouth"),
        ("Wolves", "wolverhampton-wanderers"),
        ("Coventry", "coventry-city"),
        ("Leeds", "leeds-united"),
    ],
)
def test_resolver_aliases(raw, slug):
    assert ClubResolver.from_config().resolve(raw) == slug


def test_resolver_restricts_to_known_clubs_and_prefers_ids():
    r = ClubResolver.from_config({"liverpool", "arsenal", "brighton-hove-albion"})
    r.add("liverpool", "api_football/team", 40)
    assert r.resolve("anything", "api_football/team", 40) == "liverpool"
    assert r.resolve("Brighton") == "brighton-hove-albion"
    assert r.resolve("Everton") is None


def test_fpl_short_names_resolve_without_reep(settings):
    from conftest import make_ctx
    from dugout_pipeline.adapters.fpl import FPLAdapter
    from dugout_pipeline.ids import NullIndex

    ctx = make_ctx(settings, NullIndex(), "fpl")
    a = FPLAdapter(ctx)
    clubs, _ = a.parse_clubs(
        {
            "teams": [
                {"id": 16, "code": 1, "name": "Man Utd", "short_name": "MUN"},
                {"id": 19, "code": 6, "name": "Spurs", "short_name": "TOT"},
            ]
        },
        "2026-27",
    )
    a.close()
    assert [c["club_id"] for c in clubs] == ["manchester-united", "tottenham-hotspur"]
