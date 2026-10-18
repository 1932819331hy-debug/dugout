"""Transfermarkt: three pieces.

1. `TransfermarktRefresher` (local only, weekly, `dugout refresh-values`): polite squad-page scraper, one request
   per club every few seconds, robots.txt checked. Writes a cleaned CSV of derived facts (ids, position, contract
   expiry, market value) to `data/reference/transfermarkt_squads.csv`, which is committed. Never runs in CI.
   `TransfermarktPoolRefresher` (`dugout refresh-values --pool championship`) does the same for a candidate pool
   (config `candidate_pools`): a league with no pages of its own whose players can be shortlisted elsewhere. Its
   clubs come from the competition's Transfermarkt page (one request), then one squad page per club and, where the
   pool sets `stats_season`, one performance page per club: last season's league appearances, goals, assists and
   minutes (transfermarkt-datasets has no games for a pool's league) -> `data/reference/transfermarkt_minutes.csv`.
2. `TransfermarktFileAdapter`: loads that committed CSV in CI/nightly (no scraping) -> market_values, contracts.
3. `TransfermarktDatasetsLoader`: dcaribou/transfermarkt-datasets (CC0, frozen 2026-07-06) for history/training.
"""

from __future__ import annotations

import csv
import gzip
import io
import re
from datetime import date, datetime
from pathlib import Path

from dugout_pipeline.adapters.base import DAY, TIER_DATA, SourceAdapter
from dugout_pipeline.db import upsert
from dugout_pipeline.ids import attach_catalogue
from dugout_pipeline.settings import REPO_ROOT

SQUADS_CSV = REPO_ROOT / "data" / "reference" / "transfermarkt_squads.csv"
MINUTES_CSV = REPO_ROOT / "data" / "reference" / "transfermarkt_minutes.csv"
TM_DIR = REPO_ROOT / "data" / "raw" / "transfermarkt"  # CC0 dataset tables for model training (git-ignored)
LINEUPS_SINCE = (
    "2023-07-01"  # starting positions from the last three seasons (game_lineups is 3M rows in all)
)
FIELDS = [
    "tm_player_id",
    "player_id",
    "name",
    "tm_club_id",
    "club_id",
    "club_name",  # Transfermarkt's name (candidate pools; the dataset lacks most of their clubs)
    "birth_date",
    "position",
    "joined",
    "contract_expires",
    "market_value_eur",
    "season",
    "comp",  # Transfermarkt competition id of the club's league (GB1, GB2, ...)
    "scraped_on",
    "source_url",
]


MINUTES_FIELDS = [
    "tm_player_id",
    "player_id",
    "name",
    "tm_club_id",
    "club_id",
    "comp",
    "season",  # the season the figures cover, e.g. 2025-26
    "apps",
    "goals",
    "assists",
    "minutes",
    "scraped_on",
    "source_url",
]


def parse_money(text: str) -> float | None:
    """'€28.00m' -> 28_000_000, '€800k' -> 800_000, '-' -> None."""
    m = re.search(r"([\d.,]+)\s*(bn|m|k|Th\.|Mio\.)?", text.replace("\xa0", " "))
    if not m or not any(ch.isdigit() for ch in m.group(1)):
        return None
    value = float(m.group(1).replace(",", "."))
    mult = {"bn": 1e9, "m": 1e6, "Mio.": 1e6, "k": 1e3, "Th.": 1e3}.get(m.group(2) or "", 1)
    return round(value * mult)


def parse_tm_date(text: str) -> date | None:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", text) or re.search(r"(\w{3}) (\d{1,2}), (\d{4})", text)
    if not m:
        return None
    if "/" in m.group(0):
        d, mo, y = m.groups()
        return date(int(y), int(mo), int(d))
    return datetime.strptime(m.group(0), "%b %d, %Y").date()


def parse_squad(html: bytes) -> list[dict]:
    import lxml.html

    doc = lxml.html.fromstring(html)
    headers = [th.text_content().strip() for th in doc.xpath('//table[@class="items"]/thead/tr/th')]
    col = {name: i for i, name in enumerate(headers)}
    out = []
    for tr in doc.xpath(
        '//table[@class="items"]/tbody/tr[contains(@class,"odd") or contains(@class,"even")]'
    ):
        tds = tr.xpath("./td")
        link = tr.xpath('.//td[contains(@class,"posrela")]//td[contains(@class,"hauptlink")]//a/@href')
        pid = re.search(r"/spieler/(\d+)", link[0]) if link else None
        if not pid or len(tds) < len(headers):
            continue
        name = (
            tr.xpath('.//td[contains(@class,"posrela")]//td[contains(@class,"hauptlink")]//a')[0]
            .text_content()
            .strip()
        )
        cells = {h: tds[i].text_content().strip() for h, i in col.items()}
        # the second row of the player cell is his position ("Centre-Back", "Right Winger", ...)
        pos = tr.xpath('.//td[contains(@class,"posrela")]//table[@class="inline-table"]/tr[2]/td')
        out.append(
            {
                "tm_player_id": pid.group(1),
                "name": name,
                "position": pos[0].text_content().strip() or None if pos else None,
                "birth_date": parse_tm_date(cells.get("Date of birth/Age", "")),
                "joined": parse_tm_date(cells.get("Joined", "")),
                "contract_expires": parse_tm_date(cells.get("Contract", "")),
                "market_value_eur": parse_money(cells.get("Market value", "")),
            }
        )
    return out


def _count(text: str) -> int:
    """'3.421'' -> 3421, '12' -> 12, '-' or 'Not used during this season' -> 0."""
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def parse_performance(html: bytes) -> list[dict]:
    """A club's performance page (`leistungsdaten`, /plus/1): one row per player in its squad that season, with
    league appearances, goals, assists and minutes. A player never used has one merged cell and counts 0."""
    import lxml.html

    doc = lxml.html.fromstring(html)
    tables = doc.xpath('//table[@class="items"]')
    if not tables:
        return []
    heads = []
    for th in tables[0].xpath("./thead/tr/th"):
        titles = th.xpath(".//@title")
        heads.append((titles[0] if titles else th.text_content()).strip())
    col = {name: i for i, name in enumerate(heads)}
    want = {"apps": "Appearances", "goals": "Goals", "assists": "Assists", "minutes": "Minutes played"}
    if not all(w in col for w in want.values()):
        raise ValueError(f"performance table columns changed: {heads}")
    out = []
    for tr in tables[0].xpath('./tbody/tr[contains(@class,"odd") or contains(@class,"even")]'):
        link = tr.xpath('.//td[contains(@class,"posrela")]//td[contains(@class,"hauptlink")]//a')
        pid = re.search(r"/spieler/(\d+)", link[0].get("href", "")) if link else None
        if not pid:
            continue
        tds = tr.xpath("./td")
        full = len(tds) == len(heads)  # an unused player's row merges the figures into one cell
        row = {"tm_player_id": pid.group(1), "name": link[0].text_content().strip()}
        row |= {k: _count(tds[col[h]].text_content()) if full else 0 for k, h in want.items()}
        out.append(row)
    return out


def parse_competition_clubs(html: bytes) -> list[tuple[str, str]]:
    """(Transfermarkt club id, name) of the clubs in a competition's season table (its first `items` table)."""
    import lxml.html

    doc = lxml.html.fromstring(html)
    tables = doc.xpath('//table[@class="items"]')
    if not tables:
        return []
    out = []
    for a in tables[0].xpath(
        './tbody/tr/td[contains(@class,"hauptlink")]/a[contains(@href,"/startseite/verein/")]'
    ):
        m = re.search(r"/verein/(\d+)", a.get("href", ""))
        if m and m.group(1) not in {c for c, _ in out}:
            out.append((m.group(1), a.text_content().strip()))
    return out


class TransfermarktRefresher(SourceAdapter):
    name = "transfermarkt"
    tier = TIER_DATA
    ttl = 6 * DAY
    rate, per = 1, 6.0  # one page every 6 s
    local_only = True
    base_url = "https://www.transfermarkt.com/"

    def ingest(self) -> dict[str, int]:
        con, cfg = self.ctx.con, self.ctx.league_cfg
        clubs = con.execute(
            """SELECT e.external_id, e.dugout_id FROM entity_ids e JOIN clubs c ON c.club_id = e.dugout_id
                               WHERE e.entity_type='club' AND e.provider='transfermarkt' AND c.league = ?""",
            [self.ctx.league],
        ).fetchall()
        tm_to_player = dict(
            con.execute(
                "SELECT external_id, dugout_id FROM entity_ids WHERE entity_type='player' AND provider='transfermarkt'"
            ).fetchall()
        )
        rows = []
        for tm_club, slug in clubs:
            res = self.client.get(
                f"{self.base_url}-/kader/verein/{tm_club}/saison_id/{cfg['season_start_year']}/plus/1"
            )
            for r in parse_squad(res.content):
                rows.append(
                    {
                        **r,
                        "player_id": tm_to_player.get(r["tm_player_id"]),
                        "tm_club_id": tm_club,
                        "club_id": slug,
                        "season": cfg["season"],
                        "comp": cfg["provider_ids"].get("transfermarkt"),
                        "scraped_on": res.fetched_at.date(),
                        "source_url": res.url,
                    }
                )
        # the file holds every league refreshed so far: replace this league's clubs, keep the others
        mine = {slug for _, slug in clubs}
        kept = [r for r in read_squads_csv(SQUADS_CSV) if r["club_id"] not in mine]
        write_squads_csv(kept + rows, SQUADS_CSV)
        return {"transfermarkt_squads_csv": len(rows)}


class TransfermarktPoolRefresher(SourceAdapter):
    """Squads of a candidate pool (config `candidate_pools`, e.g. the Championship): local only, like the refresher.

    No warehouse clubs exist for a pool, so its clubs come from the competition's season page on Transfermarkt; slugs
    are the club names (with the pool's `slug_suffix` where a configured league already uses the slug). Player ids
    map to Reep ids where the catalogue knows the Transfermarkt id."""

    name = "transfermarkt_pool"
    client_name = "transfermarkt"  # same host: one cache, one rate limit
    scope = "global"
    tier = TIER_DATA
    ttl = 6 * DAY
    rate, per = 1, 6.0  # one page every 6 s
    local_only = True
    base_url = "https://www.transfermarkt.com/"
    pool = "championship"

    def ingest(self) -> dict[str, int]:
        from dugout_pipeline.clubs import load_config, slugify

        cfg = load_config()["candidate_pools"][self.pool]
        comp, year = cfg["transfermarkt"], cfg["season_start_year"]
        res = self.client.get(f"{self.base_url}-/startseite/wettbewerb/{comp}/saison_id/{year}")
        clubs = parse_competition_clubs(res.content)
        if not clubs:
            raise ValueError(f"no clubs found on the {comp} page: has its layout changed?")
        taken = {c for (c,) in self.ctx.con.execute("SELECT club_id FROM clubs").fetchall()}
        ours = {r["club_id"] for r in read_squads_csv(SQUADS_CSV) if r.get("comp") != comp}
        tm_to_player = self._player_ids()
        stats = cfg.get("stats_season")  # e.g. {season: 2025-26, year: 2025}: last season's league minutes
        rows, minutes = [], []
        for tm_club, club_name in clubs:
            slug = slugify(club_name)
            if slug in taken or slug in ours:
                slug = f"{slug}-{cfg['slug_suffix']}"
            if stats:
                perf = self.client.get(
                    f"{self.base_url}-/leistungsdaten/verein/{tm_club}/reldata/{comp}%26{stats['year']}/plus/1"
                )
                for r in parse_performance(perf.content):
                    if r["apps"] > 0:
                        minutes.append(
                            {
                                **r,
                                "player_id": tm_to_player.get(r["tm_player_id"]),
                                "tm_club_id": tm_club,
                                "club_id": slug,
                                "comp": comp,
                                "season": stats["season"],
                                "scraped_on": perf.fetched_at.date(),
                                "source_url": perf.url,
                            }
                        )
            page = self.client.get(f"{self.base_url}-/kader/verein/{tm_club}/saison_id/{year}/plus/1")
            for r in parse_squad(page.content):
                rows.append(
                    {
                        **r,
                        "player_id": tm_to_player.get(r["tm_player_id"]),
                        "tm_club_id": tm_club,
                        "club_id": slug,
                        "club_name": club_name,
                        "season": cfg["season"],
                        "comp": comp,
                        "scraped_on": page.fetched_at.date(),
                        "source_url": page.url,
                    }
                )
        kept = [r for r in read_squads_csv(SQUADS_CSV) if r.get("comp") != comp]
        write_squads_csv(kept + rows, SQUADS_CSV)
        out = {"clubs": len(clubs), "transfermarkt_squads_csv": len(rows)}
        if stats:
            kept = [r for r in read_squads_csv(MINUTES_CSV) if r.get("comp") != comp]
            write_squads_csv(kept + minutes, MINUTES_CSV, MINUTES_FIELDS)
            out["transfermarkt_minutes_csv"] = len(minutes)
        return out

    def _player_ids(self) -> dict[str, str]:
        """Transfermarkt player id -> dugout (Reep) id, from the warehouse and the Reep catalogue."""
        con = self.ctx.con
        out = {
            str(a): b
            for a, b in con.execute(
                "SELECT external_id, dugout_id FROM entity_ids WHERE entity_type='player' AND provider='transfermarkt'"
            ).fetchall()
        }
        if attach_catalogue(con):
            rows = con.execute(
                "SELECT external_id, reep_id FROM reep.bridges WHERE provider='transfermarkt' AND namespace='spieler'"
            ).fetchall()
            out = {**{str(a): b for a, b in rows}, **out}
        return out


def read_squads_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_squads_csv(rows: list[dict], path: Path, fields: list[str] = FIELDS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in sorted(rows, key=lambda r: (r["club_id"], r["name"])):
            w.writerow({k: r.get(k) for k in fields})


class TransfermarktFileAdapter(SourceAdapter):
    """Reads the committed CSV; no network."""

    name = "transfermarkt_file"
    scope = "global"  # one committed file for every league
    tier = TIER_DATA

    def ingest(self, path: Path = SQUADS_CSV) -> dict[str, int]:
        if not path.exists():
            return {}
        values, contracts, n_ev = [], [], 0
        with path.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                pid = r["player_id"] or f"transfermarkt:{r['tm_player_id']}"
                scraped = date.fromisoformat(r["scraped_on"])
                fetched = datetime.combine(scraped, datetime.min.time()).replace(tzinfo=self.ctx.now.tzinfo)
                if r["market_value_eur"]:
                    values.append(
                        {
                            "player_id": pid,
                            "date": scraped,
                            "value_eur": float(r["market_value_eur"]),
                            "source": "transfermarkt",
                        }
                    )
                    self.ctx.ledger.record(
                        entity_type="player",
                        entity_id=pid,
                        metric="market_value",
                        value=float(r["market_value_eur"]),
                        unit="EUR",
                        source="transfermarkt",
                        source_tier=self.tier,
                        fetched_at=fetched,
                        source_url=r["source_url"],
                        query={
                            "kind": "file_csv",
                            "path": "data/reference/transfermarkt_squads.csv",
                            "key": {"tm_player_id": r["tm_player_id"]},
                            "column": "market_value_eur",
                        },
                    )
                    n_ev += 1
                if r["contract_expires"]:
                    contracts.append(
                        {
                            "player_id": pid,
                            "club_id": r["club_id"],
                            "source": "transfermarkt",
                            "expires": date.fromisoformat(r["contract_expires"]),
                            "fetched_at": fetched,
                        }
                    )
        n_ev += self.minutes_evidence()
        return {
            "market_values": upsert(self.ctx.con, "market_values", values),
            "contracts": upsert(self.ctx.con, "contracts", contracts),
            "evidence_ledger": n_ev,
        }

    def minutes_evidence(self, path: Path = MINUTES_CSV) -> int:
        """Ledger rows for the candidate pools' league minutes (Transfermarkt performance pages), so a shortlist that
        uses them can cite the page and the date it was read."""
        n = 0
        for r in read_squads_csv(path):
            scraped = date.fromisoformat(r["scraped_on"])
            self.ctx.ledger.record(
                entity_type="player",
                entity_id=r["player_id"] or f"transfermarkt:{r['tm_player_id']}",
                metric="league_minutes",
                value=float(r["minutes"]),
                unit="minutes",
                source="transfermarkt",
                source_tier=self.tier,
                fetched_at=datetime.combine(scraped, datetime.min.time()).replace(tzinfo=self.ctx.now.tzinfo),
                source_url=r["source_url"],
                query={
                    "kind": "file_csv",
                    "path": "data/reference/transfermarkt_minutes.csv",
                    "key": {
                        "tm_player_id": r["tm_player_id"],
                        "tm_club_id": r["tm_club_id"],
                        "season": r["season"],
                    },
                    "column": "minutes",
                },
            )
            n += 1
        return n


class TransfermarktDatasetsLoader(SourceAdapter):
    """Historical transfers & valuations from transfermarkt-datasets (CC0). Frozen at 2026-07-06."""

    name = "transfermarkt_datasets"
    scope = "global"
    tier = TIER_DATA
    ttl = 30 * DAY
    rate, per = 1, 1.0
    respect_robots = False  # public R2 bucket of a CC0 dataset
    base_url = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/"

    def table(self, name: str) -> list[dict]:
        res = self.client.get(f"{self.base_url}{name}.csv.gz")
        return list(csv.DictReader(io.StringIO(gzip.decompress(res.content).decode("utf-8"))))

    def ingest(self) -> dict[str, int]:
        con = self.ctx.con
        valuations, transfers = self.table("player_valuations"), self.table("transfers")
        con.execute("CREATE OR REPLACE TEMP TABLE _tm_map (tm_id VARCHAR PRIMARY KEY, player_id VARCHAR)")
        tm_ids = {r["player_id"] for r in valuations} | {r["player_id"] for r in transfers}
        if attach_catalogue(con):
            con.execute("""INSERT INTO _tm_map SELECT b.external_id, b.reep_id FROM reep.bridges b
                           WHERE b.provider='transfermarkt' AND b.namespace='spieler'""")
        mapping = dict(con.execute("SELECT tm_id, player_id FROM _tm_map").fetchall())
        pid = lambda tm: mapping.get(tm) or f"transfermarkt:{tm}"  # noqa: E731
        vals = [
            {
                "player_id": pid(r["player_id"]),
                "date": date.fromisoformat(r["date"][:10]),
                "value_eur": float(r["market_value_in_eur"]),
                "source": self.name,
            }
            for r in valuations
            if r.get("market_value_in_eur")
        ]
        trs = [
            {
                "player_id": pid(r["player_id"]),
                "date": date.fromisoformat(r["transfer_date"][:10]),
                "from_club": r.get("from_club_name"),
                "to_club": r.get("to_club_name"),
                "fee_eur": float(r["transfer_fee"]) if r.get("transfer_fee") else None,
                "fee_text": r.get("transfer_fee") or None,
                "kind": None,
                "source": self.name,
            }
            for r in transfers
            if r.get("transfer_date")
        ]
        return {
            "market_values": upsert(con, "market_values", vals),
            "transfers": upsert(con, "transfers", trs),
            "players_mapped": sum(1 for t in tm_ids if t in mapping),
            "players_total": len(tm_ids),
            "parquet_tables": self.save_model_tables(),
        }

    MODEL_TABLES = (
        "players",
        "transfers",
        "player_valuations",
        "appearances",
        "clubs",
        "competitions",
        "game_lineups",
    )

    def save_model_tables(self) -> int:
        """Full CC0 tables the valuation / realism / injury models train on, as Parquet under data/raw/."""
        import pandas as pd

        TM_DIR.mkdir(parents=True, exist_ok=True)
        for name in self.MODEL_TABLES:
            res = self.client.get(f"{self.base_url}{name}.csv.gz")
            df = pd.read_csv(io.BytesIO(gzip.decompress(res.content)), low_memory=False)
            if name == "game_lineups":
                # where players actually started (e.g. a "Centre-Back" who plays right-back): recent XIs only
                df = df.loc[
                    (df.type == "starting_lineup") & (df.date >= LINEUPS_SINCE),
                    ["game_id", "date", "player_id", "club_id", "position"],
                ]
            df.to_parquet(TM_DIR / f"{name}.parquet", index=False)
        return len(self.MODEL_TABLES)
