COMPOSE := docker compose --env-file .env -f infra/compose.yaml
OPENAPI_TMP := .openapi-check

.PHONY: install check backend-check frontend-check openapi openapi-check format up down logs

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

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs --follow
