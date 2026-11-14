.DEFAULT_GOAL := help
SHELL := /bin/bash
UV ?= uv
WEB := apps/panel-web
UNIT_MARKERS := not integration and not ui
ARGS ?=

.PHONY: help install lint format typecheck test test-unit test-integration ci web-install web-lint web-typecheck web-test web-build web-ci ci-all dev down migrate create-admin

help: ## list targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-18s %s\n", $$1, $$2}'

install: ## sync the uv workspace (all members, locked)
	$(UV) sync --all-packages --locked

lint: ## ruff check + format check + repo guards
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	@if ls packages/*/src/payamakyar/__init__.py apps/*/src/payamakyar/__init__.py 2>/dev/null | grep -q .; then \
	  echo "ERROR: src/payamakyar/__init__.py breaks the namespace package"; exit 1; fi
	$(UV) run python -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]"

format: ## auto-format
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

typecheck: ## mypy --strict over the workspace (member tests checked per member)
	$(UV) run mypy
	@for d in packages/*/tests apps/*/tests; do \
	  [ -d "$$d" ] || continue; \
	  find "$$d" -name '*.py' | grep -q . || continue; \
	  echo "mypy $$d"; $(UV) run mypy $$(find "$$d" -name '*.py') || exit 1; \
	done

test: ## all tests
	$(UV) run pytest $(ARGS)

test-unit: ## tests that need no Postgres/Redis/web build
	$(UV) run pytest -m "$(UNIT_MARKERS)" $(ARGS)

test-integration: ## tests that need Postgres and Redis
	$(UV) run pytest -m integration $(ARGS)

ci: export PAYAMAKYAR_TEST_REQUIRE_SERVICES := 1
ci: lint typecheck test ## python gate (missing Postgres/Redis fail instead of skipping)

web-install: ## npm ci in apps/panel-web
	@if [ -f $(WEB)/package.json ]; then npm --prefix $(WEB) ci; else echo "apps/panel-web not created yet"; fi

web-lint: ## web lint
	@if [ -f $(WEB)/package.json ]; then npm --prefix $(WEB) run lint; else echo "apps/panel-web not created yet"; fi

web-typecheck: ## web typecheck
	@if [ -f $(WEB)/package.json ]; then npm --prefix $(WEB) run typecheck; else echo "apps/panel-web not created yet"; fi

web-test: ## web tests
	@if [ -f $(WEB)/package.json ]; then npm --prefix $(WEB) test; else echo "apps/panel-web not created yet"; fi

web-build: ## web build
	@if [ -f $(WEB)/package.json ]; then npm --prefix $(WEB) run build; else echo "apps/panel-web not created yet"; fi

web-ci: web-install web-lint web-typecheck web-test web-build ## web gate

ci-all: ci web-ci ## python and web gates

dev: ## compose stack: postgres, redis, migrate, api, worker, caddy (needs Docker)
	docker compose -f infra/docker-compose.yml up --build

down: ## stop the compose stack (volumes kept; add `ARGS=-v` to drop data)
	docker compose -f infra/docker-compose.yml down $(ARGS)

create-admin: ## bootstrap an admin in the running stack: make create-admin USERNAME=ali MOBILE=09121234567
	docker compose -f infra/docker-compose.yml run --rm --no-deps api python -m payamakyar.api create-admin --username "$(USERNAME)" --mobile "$(MOBILE)"

migrate: ## alembic upgrade head (PAYAMAKYAR_DATABASE_URL)
	$(UV) run python -m payamakyar.db upgrade head
