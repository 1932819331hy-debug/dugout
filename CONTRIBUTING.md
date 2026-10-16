# Contributing to dugout

Thanks for helping. dugout is free and open source (MIT) and stays that way: free data, open-weight models, no paid
APIs, no closed-source dependencies.

## Setup

```bash
uv sync                               # Python 3.12 workspace
cp .env.example .env                  # free API keys; never commit .env
npm --prefix apps/web ci              # the website
```

Before opening a pull request:

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest                         # recorded fixtures; the network is blocked in tests
npm --prefix apps/web run lint && npm --prefix apps/web run build
npm --prefix apps/web run banned && uv run python tools/check_site_numbers.py
```

CI runs the same checks on every pull request.

## The rules that matter most

1. **The LLM never writes a number.** Agent prose uses fact codes; code fills every figure from the evidence ledger.
   A digit in published output that is not a filled placeholder is a bug, and the Stat Auditor fails the build.
2. **Nothing is published unless the Stat Auditor and Fact-Check both pass.** Anything else is withheld with the reason.
3. **Every number on the website links to its source, fetch time and verification status.**
4. **Respect robots.txt and terms of service.** Every scraper goes through `CachedClient` (cache, rate limit,
   retries, provenance). Never add a scraper for a host whose robots.txt disallows it. Never commit raw scraped data.
5. **Report results honestly.** Models ship with a reproducible backtest in `docs/backtests/`, negative results included.

`CLAUDE.md` has the full conventions (adapters, fixtures, layout); `PLAN.md` and `docs/` explain the design.

## Good first contributions

- **A new data source**: subclass `SourceAdapter`, declare `name`, `tier`, `ttl`, `rate`, implement `fetch_*` and
  `parse_*`, record trimmed fixtures with `uv run dugout record <source>`, add it to `docs/sources.md`.
- **A new club**: `uv run dugout setup-club <club>` finds and vets the club's official news source.
- **A new league**: add a block to `config/leagues.yaml` (leagues are config, not code).
- Issues labelled [good first issue](https://github.com/delta96040/dugout/labels/good%20first%20issue).

## Pull requests

Small, focused pull requests with imperative commit messages. Describe what changed and how you checked it; if a
model changes, include the backtest before and after.
