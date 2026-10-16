## What changed

## How I checked it
<!-- tests, lint, site build and digit check; for a model change, the backtest before and after -->

- [ ] `uv run ruff check . && uv run pytest`
- [ ] `npm --prefix apps/web run build` and `uv run python tools/check_site_numbers.py` (if the site or data changed)
- [ ] No API keys, `.env` or raw scraped data committed
