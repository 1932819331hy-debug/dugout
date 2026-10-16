# Project status (handoff)

Read this first in a new session, then `PLAN.md`, `CLAUDE.md`, `docs/sources.md`, `docs/backtests/README.md`.

## Where we are (2026-10-15)
- **Phase 1 — data foundation: DONE.** Nightly workflow green on GitHub Actions (repo `delta96040/dugout`, public).
  Secrets set (API_FOOTBALL_KEY, FOOTBALL_DATA_ORG_KEY, GUARDIAN_API_KEY, OPENROUTER_API_KEY, HF_TOKEN).
- **Phase 2 — core models: DONE.** Predictor beats Elo on 2024-25 and 2025-26 (all of RPS/log loss/Brier).
  Weak models improved; FootballBERT evaluated and *not adopted* (leakage). See `docs/backtests/README.md`.
- **Phase 3 — agents & verification: DONE (2026-10-16), PR delta96040/dugout#1** (branch
  `phase-3-agents-verification`). Awaiting user review / go-ahead for Phase 4. See docs/agents.md.
  - Verify: Stat Auditor, Fact-Check (DeBERTa-v3-base NLI, docs/backtests/factcheck_nli.md; BGE-small retrieval;
    passages must name every entity in the claim).
  - Models: `dugout-models publish` -> `model_outputs` (predictor, lineup, injury, roles, fingerprint, market,
    potential, fit, lookup). Training frames cached in `.cache/frames/` (warm publish ~2 min).
  - Agents: Sporting Director + 6 club specialists + Player Development + Player Fit; LLM writes with fact codes,
    drafts must pass the gate and state >= 2 facts, else templates. Ollama qwen2.5:3b by default.
  - Club news: `club_news` adapter (official club sitemaps; reproduced press credited to original outlet);
    `dugout setup-club <club> [--build]` (Wikidata P856 -> robots -> sitemap). Liverpool + Arsenal set up.
  - Eval (docs/backtests/agents_eval_*): 0 untraceable numbers everywhere. Held-out 20 questions: routing 94%,
    answer recall 93%, refusals 100%. Tuned 56-question set: 100% / 96% (LLM). The LLM's drafts pass all checks
    for ~20% of sections; templates write the rest.
  - Follow-ups: route future-tense "will ... score" to Match Predictor (held-out miss h05, left unfixed on purpose);
    nightly workflow wiring is Phase 5; LLM quality is the main lever (try a larger open-weight model hosted).
  - User feedback: GK need was a bug (fixed: peer-based needs + announced signings, e.g. Lucca Brughmans from the
    club site); Rio Ngumoha insider claim cannot be a source — sale likelihood labelled as a model estimate.

- **LLM (2026-10-16):** writer benchmark (docs/backtests/writer_llm.md) -> Poolside Laguna-S 2.1 via OpenRouter
  free tier (open weights, OpenMDW licence; uses OPENROUTER_API_KEY), local Ollama qwen2.5:3b as fallback, then
  templates. Laguna's drafts pass the gate 58% vs 17% for qwen. Gemma 4 (Apache) was rate-limited upstream; Inkling
  models are blocked for non-listed apps. Free tier has a small daily quota: LLM for showcase clubs only.
- **Phase 4 — website: IN PROGRESS (2026-10-16)**, same branch/PR #1. See docs/website.md.
  - Done: Next.js static site in apps/web (/, /clubs, /club/[slug], /methods, /scoreboard); R3F scroll story with
    pitch shader, instanced players, camera keyframes, post FX, chalk cursor, SVG fallback; every number is a <Num>
    with provenance; `key_stats` block in dossiers (audited structured facts) feeds the story; prediction_log table
    + `dugout-models scoreboard` -> data/scoreboard.json; banned-pattern script (clean);
    tools/check_site_numbers.py (0 untraceable digits). GSAP dropped (not open source) -> Lenis + own scrub.
  - Lighthouse mobile (before deferring WebGL; CPU was busy): a11y 100, SEO 100, best practices 96, performance
    61 (home) / 73 (dossier) / 79 (methods). WebGL now loads on first interaction -> re-measure.
  - **Next steps:**
    1. A background run was building template dossiers for the 18 other clubs (`dugout-agents --no-llm dossier
       <slugs>`); check data/clubs/ has 20 files, else re-run for the missing slugs.
    2. Rebuild liverpool + arsenal (`uv run dugout-agents dossier liverpool arsenal`): lineup is now always
       templated (Laguna dropped players).
    3. `npm --prefix apps/web run build`, `uv run python tools/check_site_numbers.py`, `npm --prefix apps/web run banned`,
       then Lighthouse mobile (serve apps/web/out; `npx lighthouse@13.5.0 <url> --form-factor=mobile`); target >= 90.
       If the dossier page is still < 90, look at LCP (the big bleed number / fonts).
    4. Remove the dev-only `__pitch` debug hook in components/story/Scene.tsx if unwanted (stripped in production).
    5. Commit data/clubs/*.json + data/scoreboard.json, push, update PR #1, show the user, wait for go-ahead.
  - Dev preview: .claude/launch.json "web" (npm --prefix apps/web run dev, port 3000).

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
