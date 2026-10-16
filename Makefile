# Local development on Linux/macOS. Windows: see CONTRIBUTING.md.
PY := backend/.venv/bin
DEV := $(CURDIR)/.dev
DEMO_ENV := WAMT_CLAUDE_DATA_DIR=$(DEV)/demo WAMT_DATABASE_URL=sqlite:///$(DEV)/demo.db

.PHONY: help setup demo dev-api dev-web test lint build check e2e

help:  ## List the targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

setup:  ## Create the backend venv (Python 3.12, uv) and install web dependencies
	cd backend && uv venv --python 3.12 .venv && uv pip install -e ".[dev]"
	cd web && pnpm install --frozen-lockfile

demo:  ## Generate synthetic transcripts into .dev/demo
	$(PY)/wamt demo --dir $(DEV)/demo

dev-api: demo  ## API + collector on demo data, http://localhost:8787
	$(DEMO_ENV) $(PY)/wamt serve --host 127.0.0.1 --port 8787

dev-web:  ## Vite dev server, http://localhost:5173 (proxies /api to :8787)
	cd web && pnpm dev

test:  ## Backend tests (pytest) and dashboard unit tests (Vitest)
	cd backend && .venv/bin/pytest -q
	cd web && pnpm test

lint:  ## ruff on the backend
	cd backend && .venv/bin/ruff check wamt tests

build:  ## Type-check and build the dashboard
	cd web && pnpm build

check: lint test build  ## Everything CI runs except e2e and Docker

e2e:  ## Playwright end-to-end tests (run `cd web && pnpm exec playwright install chromium` once)
	cd web && pnpm test:e2e
