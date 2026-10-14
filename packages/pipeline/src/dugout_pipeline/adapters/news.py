"""News: Guardian Open Platform (keyed), RSS feeds (keyless), optional self-hosted SearXNG, Trafilatura extraction.

Article text is stored locally only, as evidence for Fact-Check NLI. It is never republished; the site links out.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import feedparser

from dugout_pipeline.adapters.base import DAY, HOUR, TIER_JOURNALIST, SourceAdapter
from dugout_pipeline.clubs import normalise
from dugout_pipeline.db import upsert
from dugout_pipeline.http import FetchError, RobotsDisallowed

log = logging.getLogger(__name__)


def canonical_url(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", ""))


def news_id(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()[:16]


def tag_clubs(text: str, names: dict[str, str]) -> list[str]:
    """names: normalised club name/alias -> slug. Whole-word match on normalised text."""
    t = f" {normalise(text)} "
    return sorted({slug for name, slug in names.items() if f" {name} " in t})


def club_names(con, aliases: dict[str, str]) -> dict[str, str]:
    names = {}
    for slug, name in con.execute("SELECT club_id, name FROM clubs").fetchall():
        names[normalise(name)] = slug
    known = set(names.values())
    names.update({a: s for a, s in aliases.items() if s in known and len(a) > 4})
    return names


class GuardianAdapter(SourceAdapter):
    name = "guardian"
    tier = TIER_JOURNALIST
    ttl = 6 * HOUR
    rate, per = 1, 1.0  # developer tier: 60/min, 500/day (headers checked 2026-10-15)
    daily_limit = 450
    key_setting = "guardian_api_key"
    respect_robots = False  # keyed developer API governed by its terms; its robots.txt itself requires a key
    base_url = "https://content.guardianapis.com/"

    def ingest(self, days: int = 3) -> dict[str, int]:
        con = self.ctx.con
        names = club_names(con, self.ctx.clubs.aliases)
        since = (self.ctx.now - timedelta(days=days)).date().isoformat()
        rows: dict[str, dict] = {}
        for slug, name in con.execute(
            "SELECT club_id, name FROM clubs WHERE league = ?", [self.ctx.league]
        ).fetchall():
            res = self.client.get(
                f"{self.base_url}search",
                params={
                    "section": "football",
                    "q": f'"{name}"',
                    "from-date": since,
                    "page-size": 20,
                    "order-by": "newest",
                    "show-fields": "trailText,byline,bodyText",
                    "api-key": self.api_key,
                },
            )
            for item in self.parse(res.json(), names, res.fetched_at):
                rows.setdefault(item["news_id"], item)
                if slug not in rows[item["news_id"]]["club_ids"]:
                    rows[item["news_id"]]["club_ids"].append(slug)
        return {"news_items": upsert(con, "news_items", rows.values())}

    def parse(self, doc: dict[str, Any], names: dict[str, str], fetched_at: datetime) -> list[dict]:
        out = []
        for r in doc["response"]["results"]:
            f = r.get("fields", {})
            text = f"{r['webTitle']} {f.get('trailText', '')}"
            out.append(
                {
                    "news_id": news_id(r["webUrl"]),
                    "source": self.name,
                    "outlet": "The Guardian",
                    "url": r["webUrl"],
                    "title": r["webTitle"],
                    "published_at": datetime.fromisoformat(r["webPublicationDate"].replace("Z", "+00:00")),
                    "summary": _strip(f.get("trailText")),
                    "body_text": f.get("bodyText"),
                    "club_ids": tag_clubs(text, names),
                    "source_tier": self.tier,
                    "fetched_at": fetched_at,
                }
            )
        return out


class RSSAdapter(SourceAdapter):
    name = "rss"
    tier = TIER_JOURNALIST
    ttl = 1 * HOUR
    rate, per = 1, 2.0

    def ingest(self) -> dict[str, int]:
        names = club_names(self.ctx.con, self.ctx.clubs.aliases)
        rows, failed = [], []
        feeds = self.ctx.league_cfg.get("news_feeds", [])
        for feed in feeds:
            try:
                res = self.client.get(feed["url"])
            except (FetchError, RobotsDisallowed) as exc:  # one dead feed must not drop the others
                log.warning("feed %s failed: %s", feed["outlet"], exc)
                failed.append(feed["outlet"])
                continue
            rows += self.parse(res.content, feed, names, res.fetched_at)
        if feeds and len(failed) == len(feeds):
            raise FetchError(f"all RSS feeds failed: {', '.join(failed)}")
        return {
            "news_items": upsert(self.ctx.con, "news_items", {r["news_id"]: r for r in rows}.values()),
            "feeds_failed": len(failed),
        }

    def parse(
        self, content: bytes, feed: dict[str, Any], names: dict[str, str], fetched_at: datetime
    ) -> list[dict]:
        parsed = feedparser.parse(content)
        out = []
        for e in parsed.entries:
            link = e.get("link")
            if not link:
                continue
            published = None
            if e.get("published"):
                try:
                    published = parsedate_to_datetime(e["published"])
                    # feeds mix offsets and naive times; normalise to UTC so the column has one type
                    published = (
                        published.replace(tzinfo=UTC)
                        if published.tzinfo is None
                        else published.astimezone(UTC)
                    )
                except (TypeError, ValueError):
                    published = None
            summary = _strip(e.get("summary"))
            clubs = tag_clubs(f"{e.get('title', '')} {summary or ''}", names)
            if feed.get("club") and feed["club"] not in clubs:
                clubs.append(feed["club"])
            out.append(
                {
                    "news_id": news_id(link),
                    "source": self.name,
                    "outlet": feed["outlet"],
                    "url": link,
                    "title": e.get("title"),
                    "published_at": published,
                    "summary": summary,
                    "body_text": None,
                    "club_ids": clubs,
                    "source_tier": feed.get("tier", self.tier),
                    "fetched_at": fetched_at,
                }
            )
        return out


class SearxngAdapter(SourceAdapter):
    """Optional self-hosted SearXNG (SEARXNG_URL) for Fact-Check evidence retrieval. Off unless configured."""

    name = "searxng"
    tier = TIER_JOURNALIST
    ttl = 6 * HOUR
    rate, per = 1, 2.0
    respect_robots = False  # our own instance

    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        base = self.ctx.settings.searxng_url
        if not base:
            return []
        res = self.client.get(
            base.rstrip("/") + "/search", params={"q": query, "format": "json", "categories": "news"}
        )
        return res.json().get("results", [])[:max_results]

    def ingest(self) -> dict[str, int]:
        return {}  # used on demand by the Fact-Check agent (Phase 3)


class ArticleExtractor(SourceAdapter):
    """Fetches one article page (robots-checked, cached a week) and extracts the main text with Trafilatura."""

    name = "articles"
    tier = TIER_JOURNALIST
    ttl = 7 * DAY
    rate, per = 1, 3.0

    def extract(self, url: str) -> str | None:
        import trafilatura

        res = self.client.get(url)
        return trafilatura.extract(res.text, include_comments=False, include_tables=False)

    def ingest(self) -> dict[str, int]:
        return {}


def _strip(html: str | None) -> str | None:
    if not html:
        return None
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
