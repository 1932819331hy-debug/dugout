"""The only place dugout talks HTTP.

`CachedClient` wraps httpx with, in order:
  robots.txt check -> on-disk cache (TTL) -> daily budget -> token-bucket rate limit -> retries with backoff.
Every network fetch (not cache hits) is reported to a provenance sink so it can be written to the warehouse.
Secrets are passed as headers or params and are redacted from every URL that is stored or logged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import threading
import time
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

log = logging.getLogger(__name__)

SECRET_PARAMS = {"api-key", "api_key", "apikey", "key", "token", "access_token", "x-apisports-key"}
RETRY_STATUS = {429, 500, 502, 503, 504}


class RobotsDisallowed(RuntimeError):
    """The URL is disallowed by the site's robots.txt for our user agent."""


class BudgetExceeded(RuntimeError):
    """The source's daily request budget is used up."""


class FetchError(RuntimeError):
    """A request failed after all retries."""


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    query = [
        (k, "REDACTED" if k.lower() in SECRET_PARAMS else v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def build_url(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True) + [(k, str(v)) for k, v in sorted(params.items())]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@dataclass(frozen=True)
class FetchResult:
    source: str
    url: str  # redacted
    status: int
    content: bytes
    fetched_at: datetime
    from_cache: bool
    content_type: str = ""

    def json(self) -> Any:
        return json.loads(self.content)

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


@dataclass
class TokenBucket:
    """Allows `rate` requests per `per` seconds, with bursts up to `burst`."""

    rate: float
    per: float = 1.0
    burst: int = 1
    _tokens: float = field(init=False)
    _last: float = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        self._tokens = float(self.burst)
        self._last = self.clock()

    def acquire(self) -> None:
        with self._lock:
            while True:
                now = self.clock()
                self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate / self.per)
                self._last = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                self.sleep((1 - self._tokens) * self.per / self.rate)


class DailyBudget:
    """Persistent per-day request counter (UTC), so a hard API quota is never exceeded across runs."""

    def __init__(
        self, path: Path, limit: int | None, today: Callable[[], date] = lambda: datetime.now(UTC).date()
    ):
        self.path, self.limit, self._today = path, limit, today

    def _load(self) -> dict[str, int]:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def used(self) -> int:
        return self._load().get(self._today().isoformat(), 0)

    def remaining(self) -> int | None:
        return None if self.limit is None else max(0, self.limit - self.used())

    def spend(self) -> None:
        if self.limit is None:
            return
        data = self._load()
        key = self._today().isoformat()
        if data.get(key, 0) >= self.limit:
            raise BudgetExceeded(f"daily budget of {self.limit} requests used up")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({key: data.get(key, 0) + 1}))


class DiskCache:
    """Response cache keyed by (method, redacted URL, body). One JSON meta file + one body file per entry."""

    def __init__(self, root: Path):
        self.root = root

    def _paths(self, key: str) -> tuple[Path, Path]:
        d = self.root / key[:2]
        return d / f"{key}.json", d / f"{key}.bin"

    @staticmethod
    def key(method: str, url: str, body: bytes | None = None) -> str:
        h = hashlib.sha256(f"{method} {url}".encode())
        if body:
            h.update(body)
        return h.hexdigest()

    def get(self, key: str, ttl: float, now: datetime) -> tuple[dict[str, Any], bytes] | None:
        meta_p, body_p = self._paths(key)
        if not meta_p.exists() or not body_p.exists():
            return None
        meta = json.loads(meta_p.read_text())
        age = (now - datetime.fromisoformat(meta["fetched_at"])).total_seconds()
        if age > ttl:
            return None
        return meta, body_p.read_bytes()

    def delete(self, key: str) -> None:
        for path in self._paths(key):
            path.unlink(missing_ok=True)

    def put(self, key: str, meta: dict[str, Any], content: bytes) -> None:
        meta_p, body_p = self._paths(key)
        meta_p.parent.mkdir(parents=True, exist_ok=True)
        body_p.write_bytes(content)
        meta_p.write_text(json.dumps(meta))


ProvenanceSink = Callable[[FetchResult], None]


class RobotsPolicy:
    """Caches robots.txt per host (urllib.robotparser semantics): 401/403 or 5xx/timeout => disallow all;
    other 4xx (no robots.txt) => allow all."""

    def __init__(self, client: httpx.Client, user_agent: str):
        self._client, self._ua = client, user_agent
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._parsers:
            self._parsers[host] = self._load(host)
        parser = self._parsers[host]
        return True if parser is None else parser.can_fetch(self._ua, url)

    def _load(self, host: str) -> urllib.robotparser.RobotFileParser | None:
        try:
            resp = self._client.get(f"{host}/robots.txt", follow_redirects=True, timeout=15)
        except httpx.HTTPError:
            log.warning("robots.txt unreachable for %s; treating as disallowed", host)
            return _deny_all()
        if resp.status_code >= 500 or resp.status_code in (401, 403):
            return _deny_all()
        if resp.status_code >= 400 or "html" in resp.headers.get("content-type", ""):
            return None  # no robots.txt => no restrictions
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(resp.text.splitlines())
        return parser


def _deny_all() -> urllib.robotparser.RobotFileParser:
    p = urllib.robotparser.RobotFileParser()
    p.parse(["User-agent: *", "Disallow: /"])
    return p


class CachedClient:
    def __init__(
        self,
        source: str,
        *,
        cache_dir: Path,
        user_agent: str,
        ttl: float,
        rate: float,
        per: float = 1.0,
        burst: int = 1,
        daily_limit: int | None = None,
        respect_robots: bool = True,
        max_retries: int = 4,
        backoff_base: float = 1.0,
        headers: dict[str, str] | None = None,
        provenance: ProvenanceSink | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.source, self.ttl = source, ttl
        self.max_retries, self.backoff_base = max_retries, backoff_base
        self._sleep, self._now = sleep, now
        self._http = httpx.Client(
            headers={"User-Agent": user_agent, **(headers or {})},
            timeout=30,
            transport=transport,
            follow_redirects=True,
        )
        self.cache = DiskCache(cache_dir / "http" / source)
        self.bucket = TokenBucket(rate=rate, per=per, burst=burst, sleep=sleep)
        self.budget = DailyBudget(cache_dir / "budget" / f"{source}.json", daily_limit)
        self.robots = RobotsPolicy(self._http, user_agent) if respect_robots else None
        self.provenance = provenance

    def close(self) -> None:
        self._http.close()

    def forget(self, result: FetchResult, method: str = "GET") -> None:
        """Drop a cached response the caller found to be an error (an API that answers 200 with an error body,
        e.g. a suspended key), so the next run asks again instead of replaying it for the whole TTL."""
        url = getattr(result, "url", None)
        if url:
            self.cache.delete(DiskCache.key(method, url))

    def get(self, url: str, *, params: dict[str, Any] | None = None, ttl: float | None = None) -> FetchResult:
        return self.request("GET", url, params=params, ttl=ttl)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        ttl: float | None = None,
    ) -> FetchResult:
        full = build_url(url, params)
        safe = redact_url(full)
        key = DiskCache.key(method, safe, data)
        hit = self.cache.get(key, self.ttl if ttl is None else ttl, self._now())
        if hit:
            meta, content = hit
            return FetchResult(
                self.source,
                safe,
                meta["status"],
                content,
                datetime.fromisoformat(meta["fetched_at"]),
                True,
                meta.get("content_type", ""),
            )
        if self.robots and not self.robots.allowed(full):
            raise RobotsDisallowed(f"{self.source}: robots.txt disallows {safe}")
        self.budget.spend()
        resp = self._send(method, full, safe, data, headers)
        result = FetchResult(
            self.source,
            safe,
            resp.status_code,
            resp.content,
            self._now(),
            False,
            resp.headers.get("content-type", ""),
        )
        self.cache.put(
            key,
            {
                "status": result.status,
                "fetched_at": result.fetched_at.isoformat(),
                "url": safe,
                "content_type": result.content_type,
            },
            result.content,
        )
        if self.provenance:
            self.provenance(result)
        return result

    def _send(
        self, method: str, full: str, safe: str, data: bytes | None, headers: dict[str, str] | None
    ) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self.bucket.acquire()
            try:
                resp = self._http.request(method, full, content=data, headers=headers)
            except httpx.TransportError as exc:  # timeouts, connection resets
                last = exc
            else:
                if resp.status_code not in RETRY_STATUS:
                    if resp.status_code >= 400:
                        raise FetchError(f"{self.source}: HTTP {resp.status_code} for {safe}")
                    return resp
                last = FetchError(f"{self.source}: HTTP {resp.status_code} for {safe}")
                retry_after = resp.headers.get("retry-after", "")
                if retry_after.isdigit() and attempt < self.max_retries:
                    self._sleep(min(float(retry_after), 120))
                    continue
            if attempt < self.max_retries:
                self._sleep(self.backoff_base * (2**attempt) + random.uniform(0, self.backoff_base))
        raise FetchError(f"{self.source}: giving up on {safe} after {self.max_retries + 1} attempts: {last}")
