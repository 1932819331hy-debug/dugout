"""API-Football v3 (api-sports.io), free plan.

Free-plan reality (checked 2026-10-15): 100 requests/day; full seasons only for 2022–2024; for the current
season only a rolling date window of yesterday..tomorrow. So nightly we use date-window queries
(fixtures, injuries, lineups, per-fixture statistics incl. xG) and backfill 2022–2024 slowly for training.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from dugout_pipeline.adapters.base import DAY, HOUR, TIER_DATA, SourceAdapter
from dugout_pipeline.adapters.fpl import match_id
from dugout_pipeline.clubs import ClubResolver
from dugout_pipeline.db import upsert
from dugout_pipeline.http import BudgetExceeded

STATUS = {
    "FT": "finished",
    "AET": "finished",
    "PEN": "finished",
    "AWD": "finished",
    "WO": "finished",
    "PST": "postponed",
    "CANC": "postponed",
    "ABD": "postponed",
    "SUSP": "postponed",
    "NS": "scheduled",
    "TBD": "scheduled",
}
BUDGET_RESERVE = 10  # leave headroom for manual debugging and the 4-hourly injuries job


class ApiFootballAdapter(SourceAdapter):
    name = "api_football"
    tier = TIER_DATA
    ttl = 1 * HOUR
    rate, per, burst = 1, 7.0, 1  # free plan also caps per-minute calls; ~8/min is safe
    daily_limit = 100 - BUDGET_RESERVE
    key_setting = "api_football_key"
    respect_robots = False  # keyed API governed by its terms
    base_url = "https://v3.football.api-sports.io/"

    def auth_headers(self) -> dict[str, str]:
        return {"x-apisports-key": self.api_key}

    def call(self, path: str, params: dict[str, Any], ttl: float | None = None):
        res = self.client.get(self.base_url + path, params=params, ttl=ttl)
        body = res.json()
        errors = body.get("errors")
        if errors and (not isinstance(errors, list) or errors):
            raise RuntimeError(f"api_football {path}: {errors}")
        return body, res

    def ingest(self, today: date | None = None, with_lineups: bool = True) -> dict[str, int]:
        ctx = self.ctx
        ctx.load_clubs()
        today = today or ctx.now.date()
        league_id = ctx.league_cfg["provider_ids"]["api_football"]
        counts = {"match_observations": 0, "lineups": 0, "injuries": 0, "evidence_ledger": 0}

        for d in (today - timedelta(days=1), today, today + timedelta(days=1)):
            ttl = 7 * DAY if d < today else 1 * HOUR
            body, res = self.call("fixtures", {"date": d.isoformat()}, ttl=ttl)
            fixtures = [f for f in body["response"] if f["league"]["id"] == league_id]
            counts["match_observations"] += upsert(
                ctx.con, "match_observations", self.parse_fixtures(fixtures, res.fetched_at)
            )
            for f in fixtures:
                status = f["fixture"]["status"]["short"]
                mid = self._match_id(f)
                if mid is None:
                    continue
                if STATUS.get(status) == "finished":
                    stats, sres = self.call(
                        "fixtures/statistics", {"fixture": f["fixture"]["id"]}, ttl=30 * DAY
                    )
                    counts["match_observations"] += upsert(
                        ctx.con, "match_observations", self.parse_xg(mid, f, stats, sres.fetched_at)
                    )
                    counts["evidence_ledger"] += self.record_score(mid, f, res)
                if with_lineups and (STATUS.get(status) == "finished" or self._near_kickoff(f)):
                    lu, lres = self.call(
                        "fixtures/lineups",
                        {"fixture": f["fixture"]["id"]},
                        ttl=30 * DAY if STATUS.get(status) == "finished" else 10 * 60,
                    )
                    counts["lineups"] += upsert(
                        ctx.con, "lineups", self.parse_lineups(mid, lu, lres.fetched_at)
                    )

        for d in (today, today + timedelta(days=1)):
            body, res = self.call("injuries", {"date": d.isoformat()}, ttl=2 * HOUR)
            rows = self.parse_injuries(
                [i for i in body["response"] if i["league"]["id"] == league_id], res.fetched_at
            )
            counts["injuries"] += upsert(ctx.con, "injuries", rows)
        return counts

    def _near_kickoff(self, f: dict[str, Any]) -> bool:
        ko = datetime.fromisoformat(f["fixture"]["date"])
        return timedelta(minutes=-90) <= ko - self.ctx.now <= timedelta(minutes=75)

    resolver: ClubResolver | None = None

    def _slug(self, team: dict[str, Any]) -> str | None:
        return (self.resolver or self.ctx.clubs).resolve(team["name"], "api_football/team", team["id"])

    def _match_id(self, f: dict[str, Any]) -> str | None:
        home, away = self._slug(f["teams"]["home"]), self._slug(f["teams"]["away"])
        if not home or not away:
            return None
        season = f"{f['league']['season']}-{(f['league']['season'] + 1) % 100:02d}"
        return match_id(self.ctx.league, season, home, away)

    def _player(self, api_id: int | None, name: str) -> str:
        if api_id:
            row = self.ctx.con.execute(
                "SELECT dugout_id FROM entity_ids WHERE entity_type='player' AND provider='api_football' AND external_id=?",
                [str(api_id)],
            ).fetchone()
            if row:
                return row[0]
        return f"api_football:{api_id or name}"

    def parse_fixtures(self, fixtures: list[dict], fetched_at: datetime) -> list[dict]:
        rows = []
        for f in fixtures:
            mid = self._match_id(f)
            if mid:
                rows.append(
                    {
                        "match_id": mid,
                        "source": self.name,
                        "external_id": str(f["fixture"]["id"]),
                        "status": STATUS.get(f["fixture"]["status"]["short"], "live"),
                        "home_goals": f["goals"]["home"],
                        "away_goals": f["goals"]["away"],
                        "fetched_at": fetched_at,
                    }
                )
        return rows

    def parse_xg(self, mid: str, f: dict, stats: dict, fetched_at: datetime) -> list[dict]:
        xg: dict[int, float | None] = {}
        for team in stats["response"]:
            val = next((s["value"] for s in team["statistics"] if s["type"] == "expected_goals"), None)
            xg[team["team"]["id"]] = float(val) if val not in (None, "") else None
        return [
            {
                "match_id": mid,
                "source": self.name,
                "external_id": str(f["fixture"]["id"]),
                "status": STATUS.get(f["fixture"]["status"]["short"]),
                "home_goals": f["goals"]["home"],
                "away_goals": f["goals"]["away"],
                "home_xg": xg.get(f["teams"]["home"]["id"]),
                "away_xg": xg.get(f["teams"]["away"]["id"]),
                "fetched_at": fetched_at,
            }
        ]

    def parse_lineups(self, mid: str, lu: dict, fetched_at: datetime) -> list[dict]:
        rows = []
        for team in lu["response"]:
            slug = self._slug(team["team"])
            if not slug:
                continue
            for starter, key in ((True, "startXI"), (False, "substitutes")):
                for p in team.get(key) or []:
                    pl = p["player"]
                    rows.append(
                        {
                            "match_id": mid,
                            "club_id": slug,
                            "source": self.name,
                            "formation": team.get("formation"),
                            "player_id": self._player(pl.get("id"), pl["name"]),
                            "starter": starter,
                            "position": pl.get("pos"),
                            "grid": pl.get("grid"),
                            "fetched_at": fetched_at,
                        }
                    )
        return rows

    def parse_injuries(self, items: list[dict], fetched_at: datetime) -> list[dict]:
        rows = []
        for i in items:
            kind = (i["player"].get("type") or "").lower()
            rows.append(
                {
                    "player_id": self._player(i["player"].get("id"), i["player"]["name"]),
                    "club_id": self._slug(i["team"]),
                    "source": self.name,
                    "snapshot_date": fetched_at.date(),
                    "status": "doubtful" if "questionable" in kind else "unavailable",
                    "reason": i["player"].get("reason"),
                    "chance_next": None,
                    "news": i["player"].get("type"),
                    "news_added": None,
                    "expected_return": None,
                    "fetched_at": fetched_at,
                }
            )
        return rows

    def record_score(self, mid: str, f: dict, res) -> int:
        for side in ("home", "away"):
            self.ctx.ledger.record(
                entity_type="match",
                entity_id=mid,
                metric=f"{side}_goals",
                value=f["goals"][side],
                unit="goals",
                source=self.name,
                source_tier=self.tier,
                fetched_at=res.fetched_at,
                source_url=res.url,
                query={
                    "kind": "http_json",
                    "source": self.name,
                    "url": res.url,
                    "path": ["response", {"match": {"fixture.id": f["fixture"]["id"]}}, "goals", side],
                },
            )
        return 2

    def backfill_season(self, season: int, max_calls: int = 40) -> dict[str, int]:
        """Slowly backfill a free-plan season (2022–2024) for training: fixtures + per-fixture xG.

        Resumable: cached fixtures cost nothing, so repeated nightly runs walk through the season.
        Historical clubs (relegated sides) resolve by name, not only against the current 20.
        """
        league_id = self.ctx.league_cfg["provider_ids"]["api_football"]
        self.ctx.load_clubs()
        self.resolver = ClubResolver(
            aliases=self.ctx.clubs.aliases, by_provider=dict(self.ctx.clubs.by_provider)
        )
        body, res = self.call("fixtures", {"league": league_id, "season": season}, ttl=365 * DAY)
        rows, calls = self.parse_fixtures(body["response"], res.fetched_at), 0
        for f in body["response"]:
            mid = self._match_id(f)
            if not mid or STATUS.get(f["fixture"]["status"]["short"]) != "finished" or calls >= max_calls:
                continue
            try:
                stats, sres = self.call("fixtures/statistics", {"fixture": f["fixture"]["id"]}, ttl=365 * DAY)
            except BudgetExceeded:
                break
            calls += 0 if sres.from_cache else 1
            rows += self.parse_xg(mid, f, stats, sres.fetched_at)
        return {"match_observations": upsert(self.ctx.con, "match_observations", rows), "api_calls": calls}
