from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from dugout_pipeline.http import (
    BudgetExceeded,
    CachedClient,
    DailyBudget,
    FetchError,
    RobotsDisallowed,
    TokenBucket,
    redact_url,
)


def test_redact_url_hides_keys_only():
    url = "https://x.test/search?q=Liverpool&api-key=SECRET&page=2&token=abc"
    out = redact_url(url)
    assert "SECRET" not in out and "abc" not in out
    assert "q=Liverpool" in out and "page=2" in out and "api-key=REDACTED" in out


def test_token_bucket_waits_when_empty():
    t = [0.0]
    slept = []
    bucket = TokenBucket(
        rate=1,
        per=2.0,
        burst=1,
        sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)),
        clock=lambda: t[0],
    )
    bucket.acquire()
    bucket.acquire()
    assert slept and abs(sum(slept) - 2.0) < 1e-6


def test_daily_budget_persists_and_blocks(tmp_path):
    day = date(2026, 10, 15)
    b = DailyBudget(tmp_path / "b.json", 2, today=lambda: day)
    b.spend()
    DailyBudget(tmp_path / "b.json", 2, today=lambda: day).spend()  # survives a new process
    with pytest.raises(BudgetExceeded):
        b.spend()
    assert DailyBudget(tmp_path / "b.json", 2, today=lambda: date(2026, 10, 16)).remaining() == 2


def _client(tmp_path, handler, **kw):
    now = kw.pop("now", lambda: datetime(2026, 10, 15, tzinfo=UTC))
    return CachedClient(
        "t",
        cache_dir=tmp_path,
        user_agent="ua",
        ttl=3600,
        rate=1000,
        sleep=lambda s: None,
        transport=httpx.MockTransport(handler),
        now=now,
        **kw,
    )


def test_retries_then_succeeds_and_caches(tmp_path):
    calls = []

    def handler(req):
        calls.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"ok": 1})

    seen = []
    c = _client(tmp_path, handler, provenance=seen.append)
    r1 = c.get("https://api.test/data", params={"key": "SECRET"})
    assert r1.json() == {"ok": 1} and not r1.from_cache
    assert "SECRET" not in r1.url
    r2 = c.get("https://api.test/data", params={"key": "SECRET"})
    assert r2.from_cache and len(seen) == 1
    # nothing secret on disk
    for f in tmp_path.rglob("*.json"):
        assert "SECRET" not in f.read_text()


def test_cache_expires_after_ttl(tmp_path):
    now = [datetime(2026, 10, 15, tzinfo=UTC)]
    n = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        n.append(1)
        return httpx.Response(200, text="x")

    c = _client(tmp_path, handler, now=lambda: now[0])
    c.get("https://api.test/a")
    now[0] += timedelta(hours=2)
    c.get("https://api.test/a")
    assert len(n) == 2


def test_gives_up_after_retries(tmp_path):
    c = _client(
        tmp_path,
        lambda req: httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(500),
        max_retries=2,
    )
    with pytest.raises(FetchError):
        c.get("https://api.test/x")


def test_client_error_is_not_retried(tmp_path):
    hits = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        hits.append(1)
        return httpx.Response(401)

    with pytest.raises(FetchError):
        _client(tmp_path, handler).get("https://api.test/x")
    assert len(hits) == 1


def test_robots_disallow_blocks_before_any_request(tmp_path):
    hits = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /")
        hits.append(1)
        return httpx.Response(200)

    with pytest.raises(RobotsDisallowed):
        _client(tmp_path, handler).get("https://site.test/page")
    assert hits == []


def test_robots_403_means_disallow(tmp_path):
    with pytest.raises(RobotsDisallowed):
        _client(tmp_path, lambda req: httpx.Response(403)).get("https://site.test/page")


def test_budget_is_checked_before_network(tmp_path):
    hits = []

    def handler(req):
        hits.append(1)
        return httpx.Response(200, json={})

    c = _client(tmp_path, handler, daily_limit=1, respect_robots=False)
    c.get("https://api.test/1")
    with pytest.raises(BudgetExceeded):
        c.get("https://api.test/2")
    assert len(hits) == 1


def test_forget_drops_a_cached_error_reply(tmp_path):
    calls = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(1)
        body = {"errors": {"access": "suspended"}} if len(calls) == 1 else {"errors": [], "response": [1]}
        return httpx.Response(200, json=body)

    c = _client(tmp_path, handler)
    bad = c.get("https://api.test/fixtures", params={"date": "2026-10-17"})
    assert bad.json()["errors"]
    c.forget(bad)
    good = c.get("https://api.test/fixtures", params={"date": "2026-10-17"})
    assert not good.from_cache and good.json()["response"] == [1] and len(calls) == 2
