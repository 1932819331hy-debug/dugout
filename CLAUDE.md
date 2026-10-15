# dugout — project conventions

Open-source (MIT) AI sporting director. Read `PLAN.md` for phases; `docs/sources.md` for data sources.

## Hard rules
1. Free and open source only. No paid APIs, no closed-source deps.
2. **The LLM never writes a number.** Agent prose uses `{{stat:<ledger_id>}}`; code fills it from the evidence ledger.
   Any digit in final output that is not a filled placeholder is a bug (the Stat Auditor fails the build).
3. Nothing is published unless Stat Auditor **and** Fact-Check pass.
4. Every number on the website links to source, timestamp, verification status.
5. Respect robots.txt / ToS. Every scraper is cached and rate-limited. Never commit or redistribute raw scraped data
   (`data/raw/`, `.cache/`, `*.duckdb` are git-ignored). Credit StatsBomb, SkillCorner, PFF, Wyscout (Pappalardo et al. 2019).
6. Never scrape Transfermarkt from CI (`refresh-values` refuses when `CI` is set).
7. Secrets only in `.env` (git-ignored) and GitHub Actions secrets with identical names. Never print, log, or
   write key values; never put secrets in `NEXT_PUBLIC_*`.

## Layout
- `packages/pipeline` — `dugout_pipeline`: adapters (`adapters/`), HTTP core (`http.py`), DuckDB schema (`db.py`, `schema.sql`), jobs, CLI.
- `packages/verify` — `dugout_verify`: evidence ledger, Stat Auditor, Fact-Check.
- `packages/models` — `dugout_models` (predictor, ratings, roles, valuation, injury, lineup; backtests write `docs/backtests/`).
- `packages/agents` — `dugout_agents`. `tools/spadl` — isolated socceraction converter.
- `apps/web` — Next.js site, reads only static JSON in `data/`.
- `config/` — leagues/clubs YAML. Leagues are config, not code.

## Python
- Python 3.12, numpy 2, `uv` workspace. Run things with `uv run …`. Lint: `uv run ruff check .`; format: `uv run ruff format .`; tests: `uv run pytest`.
- Type hints everywhere; pydantic models for parsed rows. Small modules, no global state except settings.
- Every adapter subclasses `SourceAdapter`, declares `name`, `tier`, `ttl`, `rate`, and implements `fetch_*` + `parse_*`.
  All HTTP goes through `CachedClient` (cache, rate limit, retries, provenance). Never call `httpx` directly in an adapter.
- robots.txt is enforced for web pages (401/403/5xx on robots.txt = disallow all). Keyed/open-data APIs set
  `respect_robots = False` with a comment saying why. Never add a scraper for a host whose robots.txt disallows it.
- Tests use recorded fixtures (`tests/fixtures/<source>/`). No live network in tests: `pytest-socket` blocks it.
  Record with `uv run dugout record <source>`: URLs are redacted, headers never saved, bodies trimmed by
  `testing.TRIMMERS` to tiny excerpts (we never commit full provider responses).
- socceraction (unmaintained, pins numpy<2 / pandera 0.17) is NOT a workspace dependency. It lives in `tools/spadl`
  (own locked env) and only converts StatsBomb/Wyscout to SPADL Parquet under `data/raw/spadl/`. VAEP/xT are our own
  code in `dugout_models`. Do not add socceraction (or the `silly-kicks` fork: supply-chain risk) to the workspace.
- Windows: set `PYTHONUTF8=1` when scripting file edits in Python, or non-ASCII text gets mangled.

## Commands
- `make ingest` / `uv run dugout ingest` — full local refresh. `make test`, `make lint`.
- `make secrets` — sync `.env` → GitHub repo secrets. `scripts/check_secrets.sh` — list missing (never values).
- Windows has no `make` by default: every target is `uv run dugout <target>` underneath.

## Git
- Small commits, imperative messages. Never commit `.env`. Check `git status` before committing.
