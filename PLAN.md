# dugout — build plan

An open-source, free, multi-agent AI sporting director for the Premier League (Liverpool as showcase).
Five phases; each ends with tests green, a demo of what works, and a stop for go-ahead.

## Architecture in one picture

```
 sources ──► SourceAdapter (cache · retry · rate-limit · provenance) ──► DuckDB warehouse (Parquet)
                                   │                                         │
                                   ▼                                         ▼
                            evidence_ledger  ◄──── tools ◄──── agents (LangGraph) ──► draft with {{stat:id}}
                                   │                                                      │
                                   ▼                                                      ▼
                     Stat Auditor (no LLM)  +  Fact-Check (NLI)  ──── both pass ──►  data/clubs/<slug>.json
                                                                                          │
                                                                                          ▼
                                                                       apps/web (static, Vercel)
```

Core invariant: **the LLM never writes a number.** Every number in published output is a filled
`{{stat:<ledger_id>}}` placeholder, traceable to a ledger row (value, source URL, fetch time, query).

## Cross-cutting decisions

| Topic | Decision |
|---|---|
| Python | 3.11 (socceraction requires <3.13), `uv` workspace, one package per `packages/*` |
| Task runner | `Makefile` (Linux/macOS/CI) delegating to a Python CLI `dugout …`, so Windows works with `uv run dugout …` without `make` |
| Storage | DuckDB file in `data/warehouse/` (git-ignored) + Parquet exports; only verified JSON is committed |
| HTTP | `httpx` + on-disk cache (TTL per source) + token-bucket rate limiter + exponential backoff with jitter |
| IDs | Every player/club/manager carries a Reep ID; provider IDs live in `entity_ids` crosswalk |
| Provenance | Every adapter fetch writes a `provenance` row; every tool result writes an `evidence_ledger` row |
| Tests | `pytest`, recorded fixtures under `packages/*/tests/fixtures/`, network disabled in CI |
| Secrets | `.env` (git-ignored) locally; GitHub Actions secrets with the same names; website needs none |
| Leagues | `config/leagues.yaml`; MVP = Premier League, 20 clubs |

## Phase 1 — Data foundation
1. Repo scaffold: uv workspace, licence, `.env.example`, `.gitignore`, `CLAUDE.md`, Makefile, CLI.
2. DuckDB schema: `clubs, players, managers, matches, events, injuries, transfers, market_values,
   contracts, news_items, evidence_ledger` + support tables `entity_ids`, `provenance`, `standings`,
   `elo`, `odds`, `weather`.
3. `SourceAdapter` base: `fetch()` → cached, rate-limited, retried; `parse()` → typed rows;
   `provenance` written per request; `ttl`, `rate`, `source_tier` declared per adapter.
4. Live adapters: API-Football, FPL, football-data.org, ClubElo, Understat (soccerdata), Guardian,
   RSS (+ optional SearXNG), Trafilatura article extraction, Open-Meteo, Wikidata SPARQL, Reep.
   Secondary scrapers (Sofascore/WhoScored/ESPN/SoFIFA via soccerdata/datafc) behind the same interface, off by default.
   Local-only Transfermarkt refresher (`dugout refresh-values`), refuses to run when `CI=true`.
5. Open/historical loaders: StatsBomb (statsbombpy/kloppy), Wyscout public (socceraction loader),
   SkillCorner, Metrica, PFF WC2022 (manual download — gated by a free sign-up), transfermarkt-datasets, football-data.co.uk.
6. `docs/sources.md`: licence/terms, current free limits, cache TTL, what it feeds, request budget.
7. `dugout ingest` (= `make ingest`); adapter tests on fixtures; CI workflow; nightly workflow.
8. Repo secrets: `make secrets`, `scripts/check_secrets.sh`; create GitHub repo (with your OK).
- **Done when:** nightly workflow refreshes PL data end to end without errors.

## Phase 2 — Core models (`packages/models`, backtests in `docs/backtests/`)
- Match predictor: PyMC Dixon–Coles baseline → XGBoost on rolling xG, Elo, rest days, missing-player impact.
  Walk-forward backtests 2024–25, 2025–26; RPS / log loss / Brier vs Elo and vs closing odds.
- Player quality: VAEP + xT per 90 (socceraction) from event data.
- Roles & similarity: per-90 vectors → UMAP → HDBSCAN/GMM roles; cosine similarity; embeddings
  (FootballBERT if a usable checkpoint exists, else a small masked-player model trained on StatsBomb).
- Manager fingerprint: PPDA, field tilt, pass length, width, directness, build-up speed.
- Tactical fit, valuation (GBM on past fees), transfer realism (0–100, factor breakdown, fitted weights),
  injury risk (logistic / discrete-time survival), lineup optimiser (OR-Tools CP-SAT).
- **Done when:** predictor beats Elo on both backtest seasons.

## Phase 3 — Agents & verification (`packages/agents`, `packages/verify`)
- LangGraph: Sporting Director orchestrator + 6 specialists (Club & Tactics, Scout, Transfer & Valuation,
  Match Predictor, Lineup Selector, News & Injury). Tools return ledger ids, never raw numbers to the LLM prose.
- Renderer fills `{{stat:id}}` from ledger; any unfilled digit = failure.
- Stat Auditor (no LLM): re-run ledger queries within tolerance, stray-digit regex, cross-source checks
  (goals, minutes, injuries, fees). Fact-Check: atomic claims → type → ≥2 independent sources (aggregator
  dedupe) → source tiers → DeBERTa-v3 NLI + BGE retrieval → Verified / Conflicting / Unverified.
- Output `data/clubs/<slug>.json`. Eval: 50 hand-labelled questions; citation rate, untraceable-number rate (target 0).

## Phase 4 — Website (`apps/web`) — "The Dossier"
- Next.js App Router, Tailwind, R3F single persistent Canvas (shader pitch, instanced players, post FX,
  Catmull-Rom camera on ScrollTrigger scrub), Lenis, six pinned chapters fed by `data/clubs/liverpool.json`.
- Pages `/clubs`, `/club/[slug]`, `/methods`, `/scoreboard`; every number hoverable → source, timestamp, status.
- Static SVG fallback for reduced motion / no WebGL. Lighthouse ≥ 90 mobile, keyboard + screen-reader friendly.
- Banned-pattern review before sign-off.

## Phase 5 — Ship
- Secret check → enable `ci.yml`, `nightly.yml` (pipeline → verify → commit JSON to `data` branch),
  `injuries.yml` (every 4 h). Vercel deploy on data update.
- README (GIF, demo link, diagram, "0 untraceable numbers" badge, 3-command quick start, credits, limitations),
  CONTRIBUTING, issue templates, good-first-issue labels, MIT.

## Known risks / open questions
- **API-Football 100 req/day**: nightly budget ≈ 40 calls (fixtures, injuries, lineups for match days only);
  FPL covers most injury/minutes needs; football-data.org cross-checks results.
- **PFF WC2022 data** requires a free sign-up form; cannot be auto-downloaded in CI — loader reads a local path.
- **Transfermarkt** never scraped from CI (by design); CI reads the committed cleaned file.
- **Scraped secondary sources** (Sofascore, WhoScored…) are fragile and ToS-sensitive: off by default, local-only.
- **FootballBERT** availability to be confirmed in Phase 2; fallback is a self-trained model.
- **Guardian developer tier** is non-commercial; the project is non-commercial (Vercel Hobby too).
