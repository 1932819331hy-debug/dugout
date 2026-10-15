# Project status (handoff)

Read this first in a new session, then `PLAN.md`, `CLAUDE.md`, `docs/sources.md`, `docs/backtests/README.md`.

## Where we are (2026-10-15)
- **Phase 1 — data foundation: DONE.** Nightly workflow green on GitHub Actions (repo `delta96040/dugout`, public).
  Secrets set (API_FOOTBALL_KEY, FOOTBALL_DATA_ORG_KEY, GUARDIAN_API_KEY, OPENROUTER_API_KEY, HF_TOKEN).
- **Phase 2 — core models: DONE.** Predictor beats Elo on 2024-25 and 2025-26 (all of RPS/log loss/Brier).
  Weak models improved; FootballBERT evaluated and *not adopted* (leakage). See `docs/backtests/README.md`.
- **Next: Phase 3 — agents and verification** (LangGraph orchestrator + 6 agents, evidence ledger tools,
  Stat Auditor, Fact-Check, `data/clubs/<slug>.json`, 50-question eval). User has not yet said "go" for Phase 3.

## Key facts discovered (do not re-research)
- API-Football free plan: seasons 2022–2024 only + rolling yesterday→tomorrow date window; 100 req/day.
- Guardian dev key: 500/day, 60/min. football-data.org: 10/min.
- Understat robots.txt disallows all; Sofascore/SoFIFA/ESPN API/FotMob fail robots → not used.
- ClubElo often 502 → we compute our own Elo. Wikidata needs a User-Agent with contact URL (set in settings).
- FPL `code` = Opta id → Reep crosswalk. FPL xG starts GW16 of 2022-23 (earlier zeros = missing).
- Historical xG: vaastav/Fantasy-Premier-League (MIT) via `fpl_history` adapter.
- socceraction can't run on numpy 2 → isolated in `tools/spadl`. Do not add `silly-kicks` (supply-chain risk).
- Windows: PyTensor C compiler broken → NUTS via nutpie (`PYTENSOR_FLAGS=cxx=` set by CLI). No `make`: use `uv run dugout ...`.
- When scripting edits in Python on Windows use `PYTHONUTF8=1` (cp1252 mangles text).

## Commands
- `uv run dugout ingest [--job nightly|injuries|history] [--only a,b]`, `uv run dugout status`
- `uv run dugout load-open statsbomb|wyscout|metrica|skillcorner|pff`, `uv run dugout refresh-values` (local only)
- `uv run dugout-models backtest <model|all>`; `uv run pytest`; `uv run ruff check . && uv run ruff format .`

## Open items / ideas
- Lineups appear 20–40 min before kick-off; 4-hourly injuries job misses them → kick-off-aware schedule (Phase 5).
- Brentford venue stale in Wikidata and football-data.org (Griffin Park) — fix upstream on Wikidata.
- GitHub Actions warnings: Node 20 actions deprecated; bump action versions.
- API-Football 2022–24 fixture-stats backfill (`dugout backfill-api-football`) not scheduled; optional.
