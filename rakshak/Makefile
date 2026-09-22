# RAKSHAK developer entry points.
#
# Usage: run `make help` for the target list. All compose commands use the
# docker-compose.yml in this directory and the .env file beside it.

SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := $(shell if docker compose version >/dev/null 2>&1; then echo "docker compose"; else echo "docker-compose"; fi)
PYTHON ?= python3
BACKEND_URL ?= http://localhost:8000
DASHBOARD_URL ?= http://localhost:5173
HEALTH_RETRIES ?= 30

.PHONY: help up down seed demo test test-mobile lint migrate logs

help:
	@echo "RAKSHAK targets:"
	@echo "  make up      Build and start postgres, redis, backend, dashboard"
	@echo "  make down    Stop the stack and delete its volumes"
	@echo "  make seed    Create demo users and the MH12AB1234 hotlist entry"
	@echo "  make demo    Seed, then run the device simulator against a sample clip"
	@echo "  make test    Run the backend pytest suite inside the container"
	@echo "  make test-mobile  Run the Jest unit tests for the mobile pure logic"
	@echo "  make lint    Audit Python docstrings/function lengths and typecheck the UIs"
	@echo "  make migrate Apply Alembic migrations inside the container"
	@echo "  make logs    Follow the compose logs"

up:
	$(COMPOSE) up --build -d
	@echo "Waiting for the backend at $(BACKEND_URL) ..."
	@for attempt in $$(seq 1 $(HEALTH_RETRIES)); do \
		if curl -fsS $(BACKEND_URL)/healthz >/dev/null 2>&1; then \
			echo "Backend is healthy."; \
			break; \
		fi; \
		sleep 2; \
	done
	@echo "Waiting for the dashboard at $(DASHBOARD_URL) ..."
	@for attempt in $$(seq 1 $(HEALTH_RETRIES)); do \
		if curl -fsS $(DASHBOARD_URL) >/dev/null 2>&1; then \
			echo "Dashboard is serving."; \
			break; \
		fi; \
		sleep 2; \
	done

down:
	$(COMPOSE) down -v

seed:
	$(COMPOSE) exec -T backend $(PYTHON) scripts/seed_db.py

demo:
	bash scripts/run_demo.sh

test:
	$(COMPOSE) exec -T backend pytest -v

test-mobile:
	@if [ -d mobile/node_modules ]; then \
		cd mobile && npx jest; \
	else \
		echo "Skipping mobile tests: run 'npm install' in mobile/ first."; \
	fi

lint:
	$(PYTHON) scripts/audit_docstrings.py backend scripts
	cd dashboard && npx tsc --noEmit
	@if [ -d mobile/node_modules ]; then \
		cd mobile && npx tsc --noEmit; \
	else \
		echo "Skipping mobile typecheck: run 'npm install' in mobile/ first."; \
	fi

migrate:
	$(COMPOSE) exec -T backend alembic upgrade head

logs:
	$(COMPOSE) logs -f --tail=100
