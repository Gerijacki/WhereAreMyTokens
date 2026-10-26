# CLAUDE.md

Self-hosted token analytics for Claude Code subscriptions. Everything user-facing (UI, docs, code) is in English.

## Layout
- `backend/wamt/collector/parser.py`: pure transcript-record → facts parsing. Put format quirks here, with a test in `tests/test_parser.py`.
- `backend/wamt/collector/ingest.py`: incremental scan (byte offsets in `ingest_files`), DB writes, prompt attribution by timestamp.
- `backend/wamt/api/routes.py`: FastAPI `/api/*`. Aggregations use `usage_columns()` / `usage_dict()` from `api/queries.py`,
  and `scope()` there for the project and device filters (new endpoints should take both).
- `backend/wamt/pricing/pricing.yaml`: API prices. Never hardcode prices elsewhere.
- `backend/wamt/analytics/`: derived data. `commands.py` (command signatures), `classify.py` + `rules.yaml`
  (work categories), `cache.py` (rebuild detection), `enrich.py` (runs after each ingest batch, plus a full backfill
  whenever `ENRICH_VERSION` changes).
- `backend/wamt/insights/`: `data.py` loads a snapshot, `miners.py` has one generator per insight type,
  `artifacts.py` holds the ready-to-paste file templates, `engine.py` upserts findings and keeps their status.
- `backend/wamt/api/analytics.py`: categories, tools, cache, limits and insights endpoints.
- `backend/wamt/preferences.py` + `api/settings.py`: display preferences (currency, rate, plan, billing) saved in
  `meta`, devices API. `auth.py` also handles the UI-set password. `api/export.py`: CSV/JSON exports.
- `backend/wamt/analytics/spend.py` + `api/spend.py`: plan value (`/api/plan`, plan prices in `pricing.yaml`) and
  budgets (`/api/budgets`, alerted in `alerts.py`). Realized savings of done insights: `insights/engine.py: measure_done`.
- M4 / self-hosting: `agent.py` (spools records to disk before moving its offsets) + `api/ingest_api.py` +
  `devices.py` (multi-device push with device tokens; the device name is stored as `ChatSession.source`),
  `collector/redact.py` (secret masking, applied in the parser), `auth.py` (cookie/proxy auth middleware),
  `alerts.py`, `api/metrics.py` (Prometheus), `api/otel.py` (OTLP/JSON receiver), `analytics/blocks.py` (5h blocks),
  `demo.py` (synthetic transcripts for demos, screenshots and tests).
- `backend/wamt/migrations/`: Alembic, run programmatically by `db.migrate()` at startup.
- `web/`: React + Vite + TS + TanStack Query + ECharts (tree-shaken, SVG renderer) + Tailwind v4.
  Unit tests: Vitest, `src/**/*.test.ts`. End-to-end: Playwright in `web/e2e/` against the real backend on demo data.

## Commands
```bash
cd backend && .venv/Scripts/python -m pytest -q && .venv/Scripts/ruff check wamt tests   # Linux/macOS: .venv/bin/, or `make test lint`
cd web && pnpm build && pnpm test   # tsc + vite, Vitest
cd web && pnpm test:e2e       # Playwright; needs backend/.venv and `pnpm exec playwright install chromium`
make check e2e                # all of the above (Linux/macOS)
docker compose up -d --build  # full stack on :8787
```

## Invariants
- Never commit real transcripts, prompts, paths or tokens. Tests and screenshots use `wamt demo` or synthetic fixtures. CI runs gitleaks.
- Anything that leaves the machine (`wamt agent`) goes through `parser.slim_record()`: no file contents, tool output or model text.
- API calls are unique by `message.id`. Usage repeats on every content-block line, so merge with max, never sum.
- Code must work on both SQLite (tests, local dev) and Postgres (Docker). Dialect-specific SQL goes behind helpers like `day_bucket()`.
- Schema changes need an Alembic revision in `wamt/migrations/versions/`. Generate it by autogenerating against a DB at head (see `env.py`). Databases from before Alembic are completed and stamped `0001` by `db.migrate()`.
- Bump `PARSER_VERSION` (ingest.py) when parsing changes: every transcript is re-read, non-destructively. Never wipe tables to re-ingest, because Claude Code deletes old transcripts and the DB may be the only copy left.
- Bump `ENRICH_VERSION` (enrich.py) when categorization, signatures or cache detection change.
- e2e specs share one database and run serially: undo whatever a spec creates.
- The API serves amounts in USD; only the dashboard converts them (`money()` in `web/src/format.ts`, `toUsd()` for
  input). Never store converted amounts.
- An explicitly set `WAMT_*` environment variable beats the value saved in Settings, and locks it in the UI.
- Insight ids hash `type + key`. Keep keys stable, or users lose the done/dismissed status of their insights.
- Savings are estimates. State the assumption in the finding's summary or in the miner's docstring.
- Chart colours come from the CSS tokens in `web/src/index.css` (validated palette, separate dark steps). Model colours are keyed by model, never by rank (`modelColors.ts`).
