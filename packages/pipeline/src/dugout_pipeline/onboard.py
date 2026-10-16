"""Set dugout up for another club: find and vet its official news source, then mark it for club-level outputs.

  1. official website from Wikidata (P856), joined on the club's Transfermarkt id (P7223) as everywhere else
  2. robots.txt must allow our user agent; sitemaps come from its `Sitemap:` lines (else /sitemap.xml)
  3. the news section is the path prefix with the most recently modified article URLs in the sitemap
  4. the result is written to config/club_sites.yaml (machine-written; leagues.yaml stays hand-edited)

Deterministic on purpose: choosing a source is a decision that must be checkable, not generated.
"""

from __future__ import annotations

import logging
import re
import urllib.robotparser
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import yaml

from dugout_pipeline.adapters.base import IngestContext, SourceAdapter
from dugout_pipeline.adapters.news import sitemap_entries
from dugout_pipeline.adapters.wikidata import WikidataAdapter
from dugout_pipeline.http import FetchError

log = logging.getLogger(__name__)

WEBSITE = 'SELECT ?site WHERE { ?club wdt:P7223 "%s" . ?club wdt:P856 ?site . }'
NEWS_HINT = re.compile(r"/(?:[a-z]{2}/)?(?:news|latest-news|news-and-features|articles?|stories)/", re.I)


class SetupError(RuntimeError):
    pass


def club_sites_path(ctx: IngestContext) -> Path:
    return ctx.settings.config_dir / "club_sites.yaml"


def load_club_sites(config_dir: Path) -> list[dict[str, Any]]:
    path = config_dir / "club_sites.yaml"
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def showcase_clubs(config_dir: Path) -> list[str]:
    """Clubs that get club-specific outputs (fit, LLM-written dossiers): each league's showcase club plus clubs
    set up with `dugout setup-club` (config/club_sites.yaml)."""
    cfg = yaml.safe_load((config_dir / "leagues.yaml").read_text(encoding="utf-8"))
    clubs = {v["showcase_club"] for v in cfg.values() if isinstance(v, dict) and v.get("showcase_club")}
    return sorted(clubs | {s["club"] for s in load_club_sites(config_dir)})


class _Fetcher(SourceAdapter):
    """A polite client for the setup checks (cache, rate limit, robots for pages)."""

    name = "club_setup"
    rate, per = 1, 2.0

    def ingest(self) -> dict[str, int]:  # pragma: no cover - not an ingest source
        return {}


def official_site(ctx: IngestContext, slug: str) -> str:
    row = ctx.con.execute(
        "SELECT external_id FROM entity_ids WHERE entity_type='club' AND provider='transfermarkt' AND dugout_id = ?",
        [slug],
    ).fetchone()
    if not row:
        raise SetupError(f"{slug}: no Transfermarkt id to look the club up in Wikidata")
    wd = WikidataAdapter(ctx)
    try:
        doc = wd.sparql(WEBSITE % row[0])
    finally:
        wd.close()
    sites = [b["site"]["value"] for b in doc["results"]["bindings"]]
    if not sites:
        raise SetupError(f"{slug}: Wikidata lists no official website")
    return sorted(sites, key=lambda s: (not s.startswith("https"), len(s)))[0]


def robots(fetch: _Fetcher, site: str) -> tuple[urllib.robotparser.RobotFileParser, list[str]]:
    root = f"{urlsplit(site).scheme}://{urlsplit(site).netloc}"
    try:
        text = fetch.client.get(urljoin(root, "/robots.txt")).text
    except FetchError as exc:
        if "HTTP 404" not in str(exc):  # 401/403/5xx: treat as disallow all (project rule)
            raise SetupError(f"{root}: robots.txt unavailable ({exc}); not adding the site") from exc
        text = ""  # no robots.txt: everything allowed
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(text.splitlines())
    maps = [
        line.split(":", 1)[1].strip() for line in text.splitlines() if line.lower().startswith("sitemap:")
    ]
    return rp, maps or [urljoin(root, "/sitemap.xml")]


def news_prefix(urls: list[tuple[str, datetime | None]], now: datetime) -> str | None:
    recent = [u for u, d in urls if d and now - d <= timedelta(days=60)]
    counts = Counter(m.group(0) for u in recent if (m := NEWS_HINT.search(urlsplit(u).path)))
    return counts.most_common(1)[0][0] if counts else None


def discover(ctx: IngestContext, slug: str) -> dict[str, Any]:
    site = official_site(ctx, slug)
    fetch = _Fetcher(ctx)
    try:
        rp, maps = robots(fetch, site)
        ua = ctx.settings.user_agent
        if not rp.can_fetch(ua, site):
            raise SetupError(f"{site}: robots.txt disallows our user agent")
        best: tuple[int, str, str] | None = None
        for m in maps:
            try:
                urls = sitemap_entries(fetch.client, m)
            except (FetchError, ValueError) as exc:
                log.warning("sitemap %s: %s", m, exc)
                continue
            prefix = news_prefix(urls, ctx.now)
            if prefix:
                n = sum(1 for u, _ in urls if prefix in u)
                if best is None or n > best[0]:
                    best = (n, m, prefix)
        if best is None:
            raise SetupError(f"{site}: no news section with recent articles found in its sitemaps")
        _, sitemap, prefix = best
        sample = urljoin(site, prefix)
        if not rp.can_fetch(ua, sample):
            raise SetupError(f"{sample}: robots.txt disallows the news section")
    finally:
        fetch.close()
    name = ctx.con.execute("SELECT name FROM clubs WHERE club_id = ?", [slug]).fetchone()
    return {
        "club": slug,
        "outlet": name[0] if name else slug,
        "website": site,
        "sitemap": sitemap,
        "path_prefix": prefix,
        "checked": ctx.now.date().isoformat(),
    }


def save(ctx: IngestContext, entry: dict[str, Any]) -> Path:
    path = club_sites_path(ctx)
    sites = [s for s in load_club_sites(ctx.settings.config_dir) if s["club"] != entry["club"]] + [entry]
    header = "# Written by `dugout setup-club`: official club news sources (robots.txt checked on the date shown).\n"
    path.write_text(header + yaml.safe_dump(sorted(sites, key=lambda s: s["club"]), sort_keys=False), "utf-8")
    return path
