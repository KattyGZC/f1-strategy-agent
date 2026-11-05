COMPOSE := docker compose --env-file .env -f infra/compose.yaml
OPENAPI_TMP := .openapi-check
CLI := $(COMPOSE) run --build --rm backend python -m f1_strategy.adapters.cli
# mutmut needs fork(), so it runs on Linux in a throwaway container, on every host the same way.
MUTATION_IMAGE := ghcr.io/astral-sh/uv:0.13.5-python3.12-trixie-slim
MUTATION_STEPS := mkdir /work \
	&& tar -C /source --exclude=.venv --exclude=mutants --exclude=__pycache__ -cf - . | tar -C /work -xf - \
	&& cd /work && uv sync --locked --quiet && uv run mutmut run && uv run mutmut results
MIGRATE := $(COMPOSE) run --build --rm backend python -m f1_strategy.adapters.migrate

.PHONY: install check backend-check frontend-check mutation openapi openapi-check format up down logs migrate ingest ingest-telemetry transform

install:
	cd backend && uv sync --locked
	cd frontend && npm ci

check: backend-check frontend-check openapi-check

backend-check:
	cd backend && uv run ruff check .
	cd backend && uv run ruff format --check .
	cd backend && uv run mypy
	cd backend && uv run lint-imports
	cd backend && uv run pytest
	cd backend && uv build --quiet

frontend-check:
	cd frontend && npm run -s lint
	cd frontend && npm run -s format:check
	cd frontend && npm run -s typecheck
	cd frontend && npm run -s test
	cd frontend && npm run -s build

mutation:
	docker run --rm -v "$(CURDIR)/backend:/source:ro" $(MUTATION_IMAGE) sh -c '$(MUTATION_STEPS)'

openapi:
	cd backend && uv run python -m f1_strategy.adapters.http.openapi > ../frontend/openapi.json
	cd frontend && npm run -s openapi

openapi-check:
	rm -rf $(OPENAPI_TMP) && mkdir $(OPENAPI_TMP)
	cd backend && uv run python -m f1_strategy.adapters.http.openapi > ../$(OPENAPI_TMP)/openapi.json
	cd frontend && npx openapi-typescript ../$(OPENAPI_TMP)/openapi.json -o ../$(OPENAPI_TMP)/schema.ts --silent
	diff -u frontend/openapi.json $(OPENAPI_TMP)/openapi.json
	diff -u frontend/src/api/schema.ts $(OPENAPI_TMP)/schema.ts
	rm -rf $(OPENAPI_TMP)

format:
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && npm run -s format

up:
	$(COMPOSE) up --build --detach --wait
	$(MIGRATE)

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs --follow

migrate:
	$(MIGRATE)

ingest:
	$(if $(YEAR),,$(error YEAR is required, e.g. make ingest YEAR=2024))
	$(CLI) season --year $(YEAR)

ingest-telemetry:
	$(CLI) telemetry $(if $(SESSION),--session-key $(SESSION))

transform:
	$(if $(YEAR),,$(error YEAR is required, e.g. make transform YEAR=2024))
	$(CLI) transform --year $(YEAR)
