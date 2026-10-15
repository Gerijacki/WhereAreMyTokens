# CLAUDE.md

Self-hosted token analytics for Claude Code subscriptions. Everything user-facing (UI, docs, code) is in English.

## Layout
- `backend/wamt/collector/parser.py`: pure transcript-record → facts parsing. Put format quirks here, with a test in `tests/test_parser.py`.
- `backend/wamt/collector/ingest.py`: incremental scan (byte offsets in `ingest_files`), DB writes, prompt attribution by timestamp.
- `backend/wamt/api/routes.py`: FastAPI `/api/*`. Aggregations use `usage_columns()` / `usage_dict()` from `api/queries.py`.
- `backend/wamt/pricing/pricing.yaml`: API prices. Never hardcode prices elsewhere.
- `backend/wamt/analytics/`: derived data. `commands.py` (command signatures), `classify.py` + `rules.yaml`
  (work categories), `cache.py` (rebuild detection), `enrich.py` (runs after each ingest batch, plus a full backfill
  whenever `ENRICH_VERSION` changes).
- `backend/wamt/insights/`: `data.py` loads a snapshot, `miners.py` has one generator per insight type,
  `artifacts.py` holds the ready-to-paste file templates, `engine.py` upserts findings and keeps their status.
- `backend/wamt/api/analytics.py`: categories, tools, cache, limits and insights endpoints.
- M4 / self-hosting: `agent.py` + `api/ingest_api.py` + `devices.py` (multi-device push with device tokens),
  `collector/redact.py` (secret masking, applied in the parser), `auth.py` (cookie/proxy auth middleware),
  `alerts.py`, `api/metrics.py` (Prometheus), `api/otel.py` (OTLP/JSON receiver), `analytics/blocks.py` (5h blocks),
  `demo.py` (synthetic transcripts for demos, screenshots and tests).
- `backend/wamt/migrations/`: Alembic, run programmatically by `db.migrate()` at startup.
- `web/`: React + Vite + TS + TanStack Query + ECharts (tree-shaken, SVG renderer) + Tailwind v4.

## Commands
```bash
cd backend && .venv/Scripts/python -m pytest -q && .venv/Scripts/ruff check wamt tests
cd web && pnpm build          # tsc + vite
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
- Insight ids hash `type + key`. Keep keys stable, or users lose the done/dismissed status of their insights.
- Savings are estimates. State the assumption in the finding's summary or in the miner's docstring.
- Chart colours come from the CSS tokens in `web/src/index.css` (validated palette, separate dark steps). Model colours are keyed by model, never by rank (`modelColors.ts`).
