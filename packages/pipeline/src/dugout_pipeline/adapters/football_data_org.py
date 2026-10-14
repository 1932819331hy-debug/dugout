"""football-data.org v4 (free tier: 12 competitions incl. PL, 10 calls/min, scores slightly delayed).

Second independent source for fixtures, results and standings; also head coaches and venues.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from dugout_pipeline.adapters.base import HOUR, TIER_DATA, SourceAdapter
from dugout_pipeline.adapters.fpl import match_id
from dugout_pipeline.db import upsert

STATUS = {
    "FINISHED": "finished",
    "AWARDED": "finished",
    "IN_PLAY": "live",
    "PAUSED": "live",
    "LIVE": "live",
    "POSTPONED": "postponed",
    "SUSPENDED": "postponed",
    "CANCELLED": "postponed",
    "SCHEDULED": "scheduled",
    "TIMED": "scheduled",
}


class FootballDataOrgAdapter(SourceAdapter):
    name = "football_data_org"
    tier = TIER_DATA
    ttl = 3 * HOUR
    rate, per, burst = 8, 60.0, 1  # 10/min allowed; stay under
    key_setting = "football_data_org_key"
    respect_robots = False  # keyed API governed by its terms (robots.txt applies to crawling web pages)
    required = True
    base_url = "https://api.football-data.org/v4/"

    def auth_headers(self) -> dict[str, str]:
        return {"X-Auth-Token": self.api_key}

    def ingest(self) -> dict[str, int]:
        ctx, cfg = self.ctx, self.ctx.league_cfg
        ctx.load_clubs()
        comp, year = cfg["provider_ids"]["football_data_org"], cfg["season_start_year"]
        counts: dict[str, int] = {}

        teams = self.client.get(
            f"{self.base_url}competitions/{comp}/teams", params={"season": year}, ttl=24 * HOUR
        )
        ids, managers, venues = self.parse_teams(teams.json(), teams.fetched_at)
        counts["entity_ids"] = upsert(ctx.con, "entity_ids", ids)
        counts["managers"] = upsert(ctx.con, "managers", managers)
        for slug, (venue, address) in venues.items():
            ctx.con.execute(
                "UPDATE clubs SET venue = coalesce(venue, ?), address = ? WHERE club_id = ?",
                [venue, address, slug],
            )
        ctx.load_clubs()

        matches = self.client.get(f"{self.base_url}competitions/{comp}/matches", params={"season": year})
        obs = self.parse_matches(matches.json(), cfg["season"], matches.fetched_at)
        counts["match_observations"] = upsert(ctx.con, "match_observations", obs)
        counts["evidence_ledger"] = self.record_scores(matches.json(), cfg["season"], matches)

        table = self.client.get(f"{self.base_url}competitions/{comp}/standings", params={"season": year})
        rows = self.parse_standings(table.json(), cfg["season"], table.fetched_at)
        counts["standings"] = upsert(ctx.con, "standings", rows)
        counts["evidence_ledger"] += self.record_standings(table.json(), cfg["season"], table)
        return counts

    def _slug(self, team: dict[str, Any]) -> str | None:
        return self.ctx.clubs.resolve(team.get("name") or "", "football_data_org/team", team.get("id"))

    def parse_teams(self, doc, fetched_at: datetime) -> tuple[list[dict], list[dict], dict[str, tuple]]:
        ids, managers, venues = [], [], {}
        for t in doc["teams"]:
            slug = self._slug(t)
            if not slug:
                continue
            ids.append(
                {
                    "entity_type": "club",
                    "dugout_id": slug,
                    "provider": "football_data_org",
                    "namespace": "team",
                    "external_id": str(t["id"]),
                    "reep_id": None,
                }
            )
            venues[slug] = (t.get("venue"), t.get("address"))
            coach = t.get("coach") or {}
            if coach.get("name"):
                managers.append(
                    {
                        "manager_id": f"football_data_org:{coach['id']}",
                        "reep_id": None,
                        "name": coach["name"],
                        "birth_date": _date(coach.get("dateOfBirth")),
                        "nationality": coach.get("nationality"),
                        "club_id": slug,
                        "start_date": _date((coach.get("contract") or {}).get("start")),
                        "source": self.name,
                        "updated_at": fetched_at,
                    }
                )
        return ids, managers, venues

    def parse_matches(self, doc, season: str, fetched_at: datetime) -> list[dict]:
        rows = []
        for m in doc["matches"]:
            home, away = self._slug(m["homeTeam"]), self._slug(m["awayTeam"])
            if not home or not away:
                continue
            ft = m["score"]["fullTime"]
            rows.append(
                {
                    "match_id": match_id(self.ctx.league, season, home, away),
                    "source": self.name,
                    "external_id": str(m["id"]),
                    "status": STATUS.get(m["status"], m["status"].lower()),
                    "home_goals": ft["home"],
                    "away_goals": ft["away"],
                    "fetched_at": fetched_at,
                }
            )
        return rows

    def parse_standings(self, doc, season: str, fetched_at: datetime) -> list[dict]:
        total = next(s for s in doc["standings"] if s["type"] == "TOTAL")
        rows = []
        for r in total["table"]:
            slug = self._slug(r["team"])
            if slug:
                rows.append(
                    {
                        "league": self.ctx.league,
                        "season": season,
                        "club_id": slug,
                        "source": self.name,
                        "position": r["position"],
                        "played": r["playedGames"],
                        "won": r["won"],
                        "drawn": r["draw"],
                        "lost": r["lost"],
                        "goals_for": r["goalsFor"],
                        "goals_against": r["goalsAgainst"],
                        "points": r["points"],
                        "form": r.get("form"),
                        "fetched_at": fetched_at,
                    }
                )
        return rows

    def record_scores(self, doc, season: str, res) -> int:
        n = 0
        for m in doc["matches"]:
            if m["status"] != "FINISHED":
                continue
            home, away = self._slug(m["homeTeam"]), self._slug(m["awayTeam"])
            if not home or not away:
                continue
            for side, key in (("home_goals", "home"), ("away_goals", "away")):
                self.ctx.ledger.record(
                    entity_type="match",
                    entity_id=match_id(self.ctx.league, season, home, away),
                    metric=side,
                    value=m["score"]["fullTime"][key],
                    unit="goals",
                    source=self.name,
                    source_tier=self.tier,
                    fetched_at=res.fetched_at,
                    source_url=res.url,
                    query={
                        "kind": "http_json",
                        "source": self.name,
                        "url": res.url,
                        "path": ["matches", {"match": {"id": m["id"]}}, "score", "fullTime", key],
                    },
                )
                n += 1
        return n

    def record_standings(self, doc, season: str, res) -> int:
        n = 0
        total_idx = next(i for i, s in enumerate(doc["standings"]) if s["type"] == "TOTAL")
        for r in doc["standings"][total_idx]["table"]:
            slug = self._slug(r["team"])
            if not slug:
                continue
            for metric in ("position", "points", "goalsFor", "goalsAgainst"):
                self.ctx.ledger.record(
                    entity_type="club",
                    entity_id=slug,
                    metric=f"league_{metric}",
                    value=r[metric],
                    unit=None,
                    source=self.name,
                    source_tier=self.tier,
                    fetched_at=res.fetched_at,
                    source_url=res.url,
                    query={
                        "kind": "http_json",
                        "source": self.name,
                        "url": res.url,
                        "path": [
                            "standings",
                            total_idx,
                            "table",
                            {"match": {"team.id": r["team"]["id"]}},
                            metric,
                        ],
                    },
                )
                n += 1
        return n


def _date(s: str | None) -> date | None:
    """Accepts YYYY-MM-DD or YYYY-MM (contract dates)."""
    if not s:
        return None
    return date.fromisoformat(s if len(s) > 7 else f"{s}-01")
