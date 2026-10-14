# Every target delegates to `uv run dugout ...` so Windows users without make can run the same commands.
.PHONY: install ingest ingest-injuries ingest-history refresh-values load-open test lint format status secrets check-secrets up

install:
	uv sync

ingest:
	uv run dugout ingest --job nightly

ingest-injuries:
	uv run dugout ingest --job injuries

ingest-history:
	uv run dugout ingest --job history

# LOCAL ONLY: scrapes Transfermarkt politely, then commit data/reference/transfermarkt_squads.csv
refresh-values:
	uv run dugout refresh-values

# usage: make load-open DATASET=statsbomb LIMIT=10
load-open:
	uv run dugout load-open $(DATASET) $(if $(LIMIT),--limit $(LIMIT),)

status:
	uv run dugout status

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check . --fix

# Sync every key in .env to GitHub Actions secrets (same names). Requires `gh auth login`. Never prints values.
secrets:
	gh secret set -f .env
	bash scripts/check_secrets.sh

check-secrets:
	bash scripts/check_secrets.sh

up:
	docker compose up --build
