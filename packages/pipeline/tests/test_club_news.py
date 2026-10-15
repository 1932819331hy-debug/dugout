from datetime import UTC, datetime

from dugout_pipeline.adapters.news import ClubNewsAdapter, parse_sitemap

NOW = datetime(2026, 10, 16, tzinfo=UTC)
SITEMAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://club.test/news/match-report</loc><lastmod>2026-10-15T10:00:00Z</lastmod></url>
<url><loc>https://club.test/news/club-agree-deal-to-sign-keeper</loc><lastmod>2026-09-15T10:00:00Z</lastmod></url>
<url><loc>https://club.test/news/tag/keeper</loc><lastmod>2026-10-15T10:00:00Z</lastmod></url>
<url><loc>https://club.test/news/ancient-history</loc><lastmod>2025-01-01T10:00:00Z</lastmod></url>
<url><loc>https://club.test/tickets/sale</loc><lastmod>2026-10-15T10:00:00Z</lastmod></url>
</urlset>"""


def page(body: str, author: str = "Chris Shaw") -> str:
    return (
        f"<html><head><title>Story - Club FC</title><meta name='author' content='{author}'></head>"
        f"<body><article><h1>Story</h1><p>{body}</p></article></body></html>"
    )


def test_sitemap_keeps_recent_news_with_squad_news_first():
    urls = [u for u, _ in ClubNewsAdapter.recent(parse_sitemap(SITEMAP)[1], "/news/", NOW)]
    assert urls == [
        "https://club.test/news/club-agree-deal-to-sign-keeper",
        "https://club.test/news/match-report",
    ]


def _parse(html):
    adapter = ClubNewsAdapter.__new__(ClubNewsAdapter)
    site = {"club": "liverpool", "outlet": "Club FC"}
    return adapter.parse(html, "https://club.test/news/x", NOW, site, {}, NOW)


def test_own_announcement_is_official_tier_one():
    row = _parse(page("The club have agreed a deal to sign the goalkeeper on a long-term contract. " * 3))
    assert row["outlet"] == "Club FC" and row["source_tier"] == 1 and row["club_ids"] == ["liverpool"]


def test_reproduced_press_story_is_credited_to_the_original_outlet():
    body = "The club have agreed a fee with Genk for the goalkeeper, reports say. " * 3
    row = _parse(page(body + "</p><p>Full story: Liverpool Echo", author="This story has been reproduced"))
    assert row["outlet"] == "Liverpool Echo" and row["source_tier"] == 3


def test_setup_detects_news_section_from_recent_sitemap_entries():
    from datetime import timedelta

    from dugout_pipeline.onboard import news_prefix

    entries = [(f"https://club.test/en/news/story-{i}", NOW - timedelta(days=i)) for i in range(20)]
    entries += [(f"https://club.test/tickets/{i}", NOW) for i in range(5)]
    entries += [(f"https://club.test/articles/old-{i}", NOW - timedelta(days=400)) for i in range(50)]
    assert news_prefix(entries, NOW) == "/en/news/"
    assert news_prefix([("https://club.test/shop/x", NOW)], NOW) is None


def test_title_comes_from_the_page_title():
    html = page("Agreed a deal to sign the keeper on a long-term contract. " * 3).replace(
        "<title>Story - Club FC</title>",
        "<title>Club agree deal to sign goalkeeper Lucca Brughmans - Club FC</title>",
    )
    assert _parse(html)["title"] == "Club agree deal to sign goalkeeper Lucca Brughmans"
