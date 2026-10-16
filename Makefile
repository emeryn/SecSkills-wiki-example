.DEFAULT_GOAL := help
SHELL := /bin/sh

COMPOSE ?= docker compose
DOCKER ?= docker
UID_GID := $(shell id -u):$(shell id -g)

.PHONY: help dev up down logs test lint format build scan sbom clean-prod smoke e2e screenshots admin-password \
	import-tls backup restore-test

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dev: ## Build and run the stack in the foreground with logs
	$(COMPOSE) up --build

up: ## Start the stack in the background (same as docker compose up -d)
	$(COMPOSE) up -d

down: ## Stop the stack; data volumes are kept
	$(COMPOSE) down

logs: ## Follow the logs of every service
	$(COMPOSE) logs -f --tail=100

test: ## Run backend tests (ephemeral PostgreSQL) and frontend tests in containers
	sh scripts/test.sh

lint: ## Lint, type-check and check formatting (ruff, mypy, bandit, eslint, tsc, prettier)
	$(DOCKER) build -q -f backend/Dockerfile --target test -t wiki-backend-test .
	$(DOCKER) run --rm --network none wiki-backend-test sh -c \
		'ruff check . && ruff format --check . && mypy app tests && bandit -q -c pyproject.toml -r app'
	$(DOCKER) build -q -f frontend/Dockerfile --target test -t wiki-frontend-test .
	$(DOCKER) run --rm --network none wiki-frontend-test sh -c \
		'npm run lint && npm run typecheck && npm run format:check'

format: ## Format backend and frontend sources in place
	$(DOCKER) build -q -f backend/Dockerfile --target test -t wiki-backend-test .
	$(DOCKER) run --rm --network none --user $(UID_GID) -v "$(CURDIR)/backend:/work" -w /work \
		-e RUFF_CACHE_DIR=/tmp/ruff wiki-backend-test sh -c 'ruff check --fix . && ruff format .'
	$(DOCKER) build -q -f frontend/Dockerfile --target test -t wiki-frontend-test .
	$(DOCKER) run --rm --network none --user $(UID_GID) -v "$(CURDIR)/frontend/src:/src/src" \
		wiki-frontend-test npx prettier --write src

build: ## Audit dependencies (npm audit, pip-audit), then build every image
	$(DOCKER) build -f backend/Dockerfile --target audit .
	$(DOCKER) build -f frontend/Dockerfile --target audit .
	$(COMPOSE) build

scan: ## Scan images and configuration (Trivy; OpenSCAP when SCAP_CONTENT is set)
	sh scripts/scan.sh

sbom: ## Generate CycloneDX SBOMs; sign and attest images when COSIGN_KEY is set
	sh scripts/sbom.sh

clean-prod: ## Pre-production checks: gitleaks on tree and history
	sh scripts/clean-prod.sh

smoke: ## Check the running stack: TLS 1.3 + PQ, security headers, limits, health
	sh scripts/smoke.sh

e2e: ## End-to-end tests in Chromium against the running stack (fresh install: bootstrap flow)
	sh scripts/e2e.sh

screenshots: ## Capture docs/screenshots/*.png from an ephemeral, seeded stack (removed afterwards)
	sh scripts/screenshots.sh

admin-password: ## Show the bootstrap admin password (until it has been changed)
	$(COMPOSE) exec backend python -m app.cli admin-password

backup: ## Create an encrypted backup now (database + attachments) in the backups volume
	$(COMPOSE) exec worker python -m app.cli backup

restore-test: ## Restore the newest backup (or BACKUP=name) into a scratch database and verify it
	sh scripts/restore-test.sh

import-tls: ## Install a TLS certificate: make import-tls CERT=fullchain.pem KEY=key.pem
	@test -n "$(CERT)" -a -n "$(KEY)" || { echo "Usage: make import-tls CERT=... KEY=..."; exit 1; }
	$(COMPOSE) run --rm --no-deps -v "$(abspath $(CERT)):/import/tls.crt:ro" 		-v "$(abspath $(KEY)):/import/tls.key:ro" init 		python -m app.cli import-tls --cert /import/tls.crt --key /import/tls.key
	$(COMPOSE) restart frontend
