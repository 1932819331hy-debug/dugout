"""Wikidata SPARQL (CC0): club venues + coordinates and current head coaches (birth date, nationality).

Clubs are joined on Transfermarkt club id (P7223), which every PL club carries in both Wikidata and Reep.
"""

from __future__ import annotations

from datetime import date, datetime

from dugout_pipeline.adapters.base import DAY, TIER_DATA, SourceAdapter
from dugout_pipeline.db import upsert

QUERY = """
SELECT ?tm ?club ?venueLabel ?coord ?coach ?coachLabel ?start ?dob ?countryLabel WHERE {
  VALUES ?tm { %s }
  ?club wdt:P7223 ?tm .
  OPTIONAL { ?club wdt:P115 ?venue . ?venue wdt:P625 ?coord . }
  OPTIONAL {
    ?club p:P286 ?st . ?st ps:P286 ?coach .
    FILTER NOT EXISTS { ?st pq:P582 ?end }
    OPTIONAL { ?st pq:P580 ?start }
    OPTIONAL { ?coach wdt:P569 ?dob }
    OPTIONAL { ?coach wdt:P27 ?country }
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""


def parse_point(wkt: str) -> tuple[float, float] | None:
    # "Point(-2.96083 53.4308)" -> (lat, lon)
    if not wkt or not wkt.startswith("Point("):
        return None
    lon, lat = wkt[6:-1].split()
    return float(lat), float(lon)


class WikidataAdapter(SourceAdapter):
    name = "wikidata"
    tier = TIER_DATA
    ttl = 7 * DAY
    rate, per = 1, 5.0
    respect_robots = False  # SPARQL endpoint is an API; Wikimedia asks for a descriptive UA, which we send
    base_url = "https://query.wikidata.org/sparql"

    def ingest(self) -> dict[str, int]:
        con = self.ctx.con
        tm = dict(
            con.execute(
                "SELECT external_id, dugout_id FROM entity_ids WHERE entity_type='club' AND provider='transfermarkt'"
            ).fetchall()
        )
        if not tm:
            return {}
        values = " ".join(f'"{k}"' for k in tm)
        res = self.client.request(
            "POST",
            self.base_url,
            data=(f"query={_q(QUERY % values)}").encode(),
            headers={
                "Accept": "application/sparql-results+json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        venues, managers = self.parse(res.json(), tm, res.fetched_at)
        for slug, (name, lat, lon) in venues.items():
            con.execute(
                "UPDATE clubs SET venue = coalesce(?, venue), lat = ?, lon = ? WHERE club_id = ?",
                [name, lat, lon, slug],
            )
        return {"clubs": len(venues), "managers": upsert(con, "managers", managers)}

    def parse(self, doc: dict, tm: dict[str, str], fetched_at: datetime):
        venues, managers = {}, {}
        for b in doc["results"]["bindings"]:
            slug = tm.get(b["tm"]["value"])
            if not slug:
                continue
            if "coord" in b and (pt := parse_point(b["coord"]["value"])):
                venues[slug] = (b.get("venueLabel", {}).get("value"), *pt)
            if "coach" in b:
                qid = b["coach"]["value"].rsplit("/", 1)[-1]
                start = b.get("start", {}).get("value")
                prev = managers.get(slug)
                # several open-ended statements can exist; keep the most recent start
                if prev and prev["start_date"] and start and str(prev["start_date"]) >= start[:10]:
                    continue
                managers[slug] = {
                    "manager_id": f"wikidata:{qid}",
                    "reep_id": None,
                    "name": b["coachLabel"]["value"],
                    "birth_date": date.fromisoformat(b["dob"]["value"][:10]) if "dob" in b else None,
                    "nationality": b.get("countryLabel", {}).get("value"),
                    "club_id": slug,
                    "start_date": date.fromisoformat(start[:10]) if start else None,
                    "source": self.name,
                    "updated_at": fetched_at,
                }
        return venues, list(managers.values())


def _q(s: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(s)
