# dugout

An open-source AI sporting director for the Premier League. Free data, open-weight models, and a hard rule:
**the LLM never writes a number** — every figure is filled from an evidence ledger and checked by two verifiers.

> Work in progress. See [PLAN.md](PLAN.md) for the phases and [docs/sources.md](docs/sources.md) for every data source.

## Quick start

```bash
git clone <this repo> && cd dugout
cp .env.example .env        # add your free API keys
uv sync && uv run dugout ingest   # or: make ingest
```

`uv run dugout status` shows table counts, API budgets and the last run of each source.

## Data credits

StatsBomb Open Data · Wyscout public dataset (Pappalardo et al., 2019, *Scientific Data* 6:236) · SkillCorner Open Data ·
Metrica Sports sample data · PFF FC World Cup 2022 · Reep Register (CC0) · transfermarkt-datasets (CC0) ·
football-data.co.uk · football-data.org · API-Football · Fantasy Premier League · ClubElo · Open-Meteo (CC-BY 4.0) ·
Wikidata (CC0) · postcodes.io (OGL) · The Guardian Open Platform.

## Licence

MIT
