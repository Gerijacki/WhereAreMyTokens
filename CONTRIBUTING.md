# Contributing

Thanks for helping make Claude Code usage easier to understand. Bug reports, insight ideas, pricing updates and pull requests are all welcome.

## Ground rules

- **Never commit real transcripts, prompts or tokens.** Tests and screenshots use synthetic data: `wamt demo` or the fixtures in `backend/tests/fixtures`. CI runs a secret scan on every push.
- Keep the backend working on **both SQLite and PostgreSQL**.
- Schema changes go through Alembic: `backend/wamt/migrations/versions/`.
- Every insight must state how its saving is estimated.

## Setup

On Linux and macOS, `make setup` creates the backend virtualenv (with [uv](https://docs.astral.sh/uv/)) and installs the web dependencies. Then `make dev-api` and `make dev-web` run the stack on demo data. Run `make help` to list every target. By hand:

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"     # Windows: .venv\Scripts\
.venv/bin/pytest -q
.venv/bin/ruff check wamt tests

cd ../web
pnpm install
pnpm build          # type-checks too
pnpm dev            # http://localhost:5173, proxies /api to :8787
pnpm test           # unit tests (Vitest), next to the code as src/**/*.test.ts
```

## End-to-end tests

`web/e2e/` holds Playwright tests that drive the built dashboard against the real backend. `e2e/server.mjs` generates demo data with a fixed seed, ingests and analyzes it, then serves it with the collector off, so runs are reproducible. A second server runs with a password to cover the login flow.

```bash
cd web
pnpm exec playwright install chromium   # once
pnpm test:e2e                           # builds the dashboard, starts both servers, runs the specs
```

The servers use `backend/.venv`, or the `wamt` executable in `WAMT_BIN`. Specs share one database and run one at a time, so a spec that creates something (a budget, an insight status) must undo it. Add a spec for every user-visible flow you build.

To get realistic data without your own, run `wamt demo --dir /tmp/demo` and then `WAMT_CLAUDE_DATA_DIR=/tmp/demo wamt serve`.

## Common changes

| You want to… | Edit |
|---|---|
| Update model prices | `backend/wamt/pricing/pricing.yaml`. Add the source link in the PR. |
| Improve categorization | `backend/wamt/analytics/rules.yaml`, plus a case in `tests/test_analytics.py` |
| Handle a new transcript format quirk | `backend/wamt/collector/parser.py`, plus a test, and bump `PARSER_VERSION` in `ingest.py` |
| Add an insight detector | A generator in `backend/wamt/insights/miners.py` added to `MINERS`, a planted pattern in `wamt/demo.py`, and a test |
| Add a migration | `alembic revision --autogenerate` against a database at head (see `wamt/migrations/env.py`) |
| Update plan prices | The `plans` section of `backend/wamt/pricing/pricing.yaml` (per currency and billing period) |
| Add a setting | `wamt/preferences.py` (`FIELDS`, validation), a field in `config.py`, a control in `web/src/pages/Settings.tsx` |

## Pull requests

- Keep PRs focused and describe the user-visible change.
- `pytest`, `ruff`, `pnpm build`, `pnpm test` and `pnpm test:e2e` must pass (`make check e2e`). CI also smoke-tests the Docker image on demo data.
- For UI changes, add a screenshot taken from **demo data**.
